"""Job-private skill lifecycle and explicit global promotion for Work."""

from __future__ import annotations

import copy
import json
import os
import secrets
from typing import Any

from .store_common import _SKILL_STATUSES
from .validation import (
    WorkConflictError,
    WorkNotFoundError,
    WorkValidationError,
    clean_json_object,
    clean_public_error,
    clean_text,
    new_id,
    require_safe_id,
    utc_now_iso,
)


class WorkSkillMixin:
    def _publish_global_skill_bundle(self, global_id: str, skill: dict[str, Any]) -> dict[str, str]:
        """Write an approved skill into Thomas's native global discovery root."""

        skill_dir = self.global_skills_root / require_safe_id(global_id, field="global_skill_id")
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        description = clean_text(skill.get("description"), field="description", max_length=2_000)
        instructions = clean_text(skill.get("skill_ref"), field="skill_ref", max_length=4_000)
        body = "\n".join(
            [
                "---",
                f"name: {json.dumps(global_id, ensure_ascii=False)}",
                f"description: {json.dumps(description or 'Promoted Thomas Work skill', ensure_ascii=False)}",
                "---",
                "",
                f"# {skill.get('name') or global_id}",
                "",
                description or "Use this workflow when its name and job-derived purpose match the request.",
                "",
                "## Instructions",
                "",
                instructions
                or description
                or "Follow the promoted job workflow and verify the result before completion.",
                "",
            ]
        )
        temp = skill_dir / f".SKILL.{secrets.token_hex(6)}.tmp"
        try:
            with temp.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, skill_file)
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise WorkValidationError("global skill bundle could not be published") from exc
        return {"bundle_path": str(skill_dir), "skill_file": str(skill_file)}

    def list_skills(self, app_id: str, job_id: str) -> list[dict[str, Any]]:
        return self.get_job(app_id, job_id)["private_skills"]

    def list_global_skills(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = [copy.deepcopy(row) for row in self._state["global_skills"].values()]
        return sorted(rows, key=lambda row: (str(row.get("name") or "").lower(), str(row.get("id") or "")))

    def create_skill(self, app_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name = clean_text(payload.get("name"), field="name", required=True, max_length=160)
        skill_id = require_safe_id(payload.get("id"), field="id") if payload.get("id") else new_id("skill")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            if any(row.get("id") == skill_id for row in job["private_skills"]):
                raise WorkConflictError("private skill id already exists")
            now = utc_now_iso()
            skill = {
                "id": skill_id,
                "name": name,
                "description": clean_text(payload.get("description"), field="description"),
                "skill_ref": clean_text(payload.get("skill_ref"), field="skill_ref", max_length=1_000),
                "scope": "job_private",
                "status": "draft",
                "promotion": {"state": "job_private", "target": "", "requested_at": "", "decided_at": ""},
                "metadata": clean_json_object(payload.get("metadata"), field="metadata"),
                "created_at": now,
                "updated_at": now,
            }
            job["private_skills"].append(skill)
            job["updated_at"] = now
            self._append_activity(
                job,
                kind="skill_learned",
                state="complete",
                summary=f"Learned private skill: {name}",
                details={"skill_id": skill_id, "scope": "job_private"},
            )
            return skill

        return self._mutate(operation)

    def update_skill(self, app_id: str, job_id: str, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        safe_id = require_safe_id(skill_id, field="skill_id")
        if "promotion_state" in payload or "promotion_target" in payload:
            raise WorkValidationError("skill promotion must use the explicit request and approval endpoints")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            skill = next((row for row in job["private_skills"] if row.get("id") == safe_id), None)
            if not isinstance(skill, dict):
                raise WorkNotFoundError("private skill not found")
            if "status" in payload:
                status = clean_text(payload["status"], field="status").lower()
                if status not in _SKILL_STATUSES:
                    raise WorkValidationError("invalid private skill status")
                skill["status"] = status
            skill["updated_at"] = utc_now_iso()
            job["updated_at"] = skill["updated_at"]
            return skill

        return self._mutate(operation)

    def request_skill_promotion(self, app_id: str, job_id: str, skill_id: str) -> dict[str, Any]:
        """Record an explicit promotion request without changing skill scope."""
        safe_id = require_safe_id(skill_id, field="skill_id")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            skill = next((row for row in job["private_skills"] if row.get("id") == safe_id), None)
            if not isinstance(skill, dict):
                raise WorkNotFoundError("private skill not found")
            if skill.get("promotion", {}).get("state") == "approved":
                raise WorkConflictError("skill is already in the global library")
            now = utc_now_iso()
            skill["promotion"].update(
                {"state": "requested", "target": "global_library", "requested_at": now, "decided_at": ""}
            )
            skill["updated_at"] = now
            job["updated_at"] = now
            self._append_activity(
                job,
                kind="skill_promotion_requested",
                state="waiting",
                summary=f"Requested global promotion: {skill['name']}",
                details={"skill_id": safe_id},
            )
            return skill

        return self._mutate(operation)

    def approve_skill_promotion(
        self,
        app_id: str,
        job_id: str,
        skill_id: str,
        *,
        approved_by: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Copy a requested private skill into the global library after approval.

        The original remains in the job for provenance. Its scope is deliberately
        not changed until this second, explicit action succeeds.
        """

        approver = clean_text(approved_by, field="approved_by", required=True, max_length=160)
        safe_id = require_safe_id(skill_id, field="skill_id")

        def operation(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            job = self._job(state, app_id, job_id)
            skill = next((row for row in job["private_skills"] if row.get("id") == safe_id), None)
            if not isinstance(skill, dict):
                raise WorkNotFoundError("private skill not found")
            if skill.get("promotion", {}).get("state") != "requested":
                raise WorkConflictError("skill promotion must be requested before approval")
            now = utc_now_iso()
            global_id = f"global-{safe_id}"
            global_skill = {
                "id": global_id,
                "name": skill["name"],
                "description": skill.get("description", ""),
                "skill_ref": skill.get("skill_ref", ""),
                "scope": "global",
                "status": "active",
                "source": {"app_id": app_id, "job_id": job_id, "skill_id": safe_id},
                "approved_by": approver,
                "created_at": now,
                "updated_at": now,
            }
            global_skill.update(self._publish_global_skill_bundle(global_id, skill))
            state["global_skills"][global_id] = global_skill
            skill["promotion"] = {
                **skill["promotion"],
                "state": "approved",
                "target": global_id,
                "decided_at": now,
                "approved_by": approver,
            }
            skill["updated_at"] = now
            job["activity"].append(
                {
                    "id": new_id("activity"),
                    "type": "skill_promoted",
                    "state": "complete",
                    "summary": f"Promoted {skill['name']} to the global skill library",
                    "details": {"global_skill_id": global_id, "approved_by": approver},
                    "created_at": now,
                }
            )
            job["updated_at"] = now
            return skill, global_skill

        return self._mutate(operation)

    def list_activity(self, app_id: str, job_id: str) -> list[dict[str, Any]]:
        rows = self.get_job(app_id, job_id)["activity"]
        for row in rows:
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            if details.get("error"):
                details["error"] = clean_public_error(details["error"])
            row["details"] = details
        return rows

    def record_activity(
        self,
        app_id: str,
        job_id: str,
        *,
        kind: str,
        state_value: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_kind = require_safe_id(kind, field="kind")
        safe_state = require_safe_id(state_value, field="state")
        safe_summary = clean_text(summary, field="summary", required=True, max_length=500)

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            row = self._append_activity(
                job,
                kind=safe_kind,
                state=safe_state,
                summary=safe_summary,
                details=clean_json_object(details, field="details"),
            )
            job["updated_at"] = row["created_at"]
            return row

        return self._mutate(operation)
