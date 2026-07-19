"""Job lifecycle, memory, dashboards, and artifacts for Work."""

from __future__ import annotations

import copy
from typing import Any

from .store_common import _JOB_STATUSES, _clean_object_list, _clean_settings
from .store_workflows import normalize_workflow_memory
from .validation import (
    WorkConflictError,
    WorkNotFoundError,
    WorkValidationError,
    clean_artifact_reference,
    clean_json_object,
    clean_string_list,
    clean_text,
    new_id,
    require_safe_id,
    utc_now_iso,
)


class WorkJobMixin:
    def list_jobs(self, app_id: str, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            app = self._app(self._state, app_id)
            rows = [copy.deepcopy(row) for row in app.get("jobs", {}).values() if isinstance(row, dict)]
        if not include_archived:
            rows = [row for row in rows if row.get("status") != "archived"]
        return sorted(rows, key=lambda row: (str(row.get("name") or "").lower(), str(row.get("id") or "")))

    def get_job(self, app_id: str, job_id: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._job(self._state, app_id, job_id))

    def create_job(self, app_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        job, _created = self.create_job_with_status(app_id, payload)
        return job

    def create_job_with_status(
        self,
        app_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Create once and report whether this call performed the mutation."""

        name = clean_text(payload.get("name"), field="name", required=True, max_length=160)
        job_id = require_safe_id(payload.get("id"), field="id") if payload.get("id") else new_id("job")
        history_session_id = clean_text(
            payload.get("history_session_id"),
            field="history_session_id",
            max_length=240,
        )
        onboarding_key = clean_text(payload.get("idempotency_key"), field="idempotency_key", max_length=240)
        if onboarding_key and not history_session_id:
            raise WorkValidationError("idempotency_key requires history_session_id")
        metadata = clean_json_object(payload.get("metadata"), field="metadata")
        if "onboarding_key" in metadata:
            raise WorkValidationError("onboarding_key is server-owned")
        now = utc_now_iso()

        def operation(state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            app = self._app(state, app_id)
            if app.get("status") == "archived":
                raise WorkConflictError("archived work apps cannot receive jobs")
            if onboarding_key:
                matches = [
                    row
                    for row in app["jobs"].values()
                    if isinstance(row, dict)
                    and isinstance(row.get("metadata"), dict)
                    and row["metadata"].get("onboarding_key") == onboarding_key
                ]
                if len(matches) > 1:
                    raise WorkConflictError("onboarding idempotency key is not unique")
                if matches:
                    if str((matches[0].get("history") or {}).get("session_id") or "") != history_session_id:
                        raise WorkConflictError("onboarding idempotency key belongs to another session")
                    return matches[0], False
            if job_id in app["jobs"]:
                raise WorkConflictError("work job id already exists")
            goal = clean_text(payload.get("goal") or app.get("goal"), field="goal", required=True)
            job = {
                "id": job_id,
                "app_id": app["id"],
                "name": name,
                "goal": goal,
                "description": clean_text(payload.get("description"), field="description"),
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "settings": _clean_settings(payload.get("settings")),
                "history": {
                    "session_id": history_session_id or f"work:{app['id']}:{job_id}",
                    "message_count": 0,
                    "last_message_at": "",
                    "title": name,
                    "metadata": {},
                },
                "memory": {
                    "scope": f"work/{app['id']}/{job_id}",
                    "summary": "",
                    "workflows": [],
                    "metadata": {},
                },
                "dashboard": {"metrics": [], "sections": [], "artifacts": []},
                "connector_bindings": [],
                "private_skills": [],
                "automations": [],
                "activity": [
                    {
                        "id": new_id("activity"),
                        "type": "job_created",
                        "state": "complete",
                        "summary": "Job created",
                        "details": {},
                        "created_at": now,
                    }
                ],
                "metadata": {**metadata, **({"onboarding_key": onboarding_key} if onboarding_key else {})},
            }
            app["jobs"][job_id] = job
            app["updated_at"] = now
            return job, True

        return self._mutate(operation)

    def rollback_failed_job_creation(self, app_id: str, job_id: str) -> None:
        """Compensate a cross-store history-transfer failure.

        This is intentionally narrow: only a pristine, just-created job with
        the single ``job_created`` activity may be removed.
        """

        def operation(state: dict[str, Any]) -> None:
            app = self._app(state, app_id)
            job = self._job(state, app_id, job_id)
            activity = job.get("activity") if isinstance(job.get("activity"), list) else []
            if len(activity) != 1 or str(activity[0].get("type") or "") != "job_created":
                raise WorkConflictError("failed job creation can no longer be rolled back")
            del app["jobs"][job_id]
            app["updated_at"] = utc_now_iso()

        self._mutate(operation)

    def update_job(self, app_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            if job.get("status") == "archived":
                raise WorkConflictError("archived jobs cannot be changed")
            for field, required, limit in (("name", True, 160), ("goal", True, 4_000), ("description", False, 4_000)):
                if field in payload:
                    job[field] = clean_text(payload[field], field=field, required=required, max_length=limit)
            if "settings" in payload:
                job["settings"] = _clean_settings(payload["settings"])
            if "metadata" in payload:
                metadata = clean_json_object(payload["metadata"], field="metadata")
                if "onboarding_key" in metadata:
                    raise WorkValidationError("onboarding_key is server-owned")
                onboarding_key = str(job["metadata"].get("onboarding_key") or "")
                job["metadata"] = {
                    **metadata,
                    **({"onboarding_key": onboarding_key} if onboarding_key else {}),
                }
            job["updated_at"] = utc_now_iso()
            return job

        return self._mutate(operation)

    def set_job_status(self, app_id: str, job_id: str, status: str) -> dict[str, Any]:
        normalized = clean_text(status, field="status").lower()
        if normalized not in _JOB_STATUSES:
            raise WorkValidationError("job status must be active, paused, or archived")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            if job.get("status") == "archived" and normalized != "archived":
                raise WorkConflictError("archived jobs cannot be resumed")
            job["status"] = normalized
            job["updated_at"] = utc_now_iso()
            self._append_activity(
                job,
                kind="job_status",
                state="complete",
                summary=f"Job {normalized}",
                details={"status": normalized},
            )
            return job

        return self._mutate(operation)

    def update_history(self, app_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if "session_id" in payload:
            raise WorkValidationError("history session_id is server-owned and cannot be changed")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            history = job["history"]
            if "message_count" in payload:
                count = payload["message_count"]
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise WorkValidationError("message_count must be a non-negative integer")
                history["message_count"] = count
            if "last_message_at" in payload:
                history["last_message_at"] = clean_text(
                    payload["last_message_at"], field="last_message_at", max_length=80
                )
            if "title" in payload:
                history["title"] = clean_text(payload["title"], field="title", max_length=160)
            if "metadata" in payload:
                history["metadata"] = clean_json_object(payload["metadata"], field="metadata")
            job["updated_at"] = utc_now_iso()
            return history

        return self._mutate(operation)

    def update_job_memory(self, app_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if "scope" in payload:
            raise WorkValidationError("job memory scope is server-owned and cannot be changed")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            memory = job["memory"]
            if "summary" in payload:
                memory["summary"] = clean_text(payload["summary"], field="summary", max_length=8_000)
            if "workflows" in payload:
                memory["workflows"] = _clean_object_list(payload["workflows"], field="workflows")
                normalize_workflow_memory(memory)
            if "metadata" in payload:
                metadata = clean_json_object(payload["metadata"], field="metadata")
                if "active_workflow_id" in metadata:
                    raise WorkValidationError("active_workflow_id is server-owned; use workflow selection")
                active_workflow_id = str(memory["metadata"].get("active_workflow_id") or "")
                memory["metadata"] = {**metadata, "active_workflow_id": active_workflow_id}
            job["updated_at"] = utc_now_iso()
            self._append_activity(job, kind="memory_updated", state="complete", summary="Job memory updated")
            return memory

        return self._mutate(operation)

    def update_job_dashboard(self, app_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            dashboard = job["dashboard"]
            if "metrics" in payload:
                dashboard["metrics"] = _clean_object_list(payload["metrics"], field="metrics")
            if "sections" in payload:
                dashboard["sections"] = _clean_object_list(payload["sections"], field="sections")
            # AI-designed surfaces: a one-line headline, action buttons bound to
            # the job's OWN workflows, and inboxes. Same bounded-object handling
            # as metrics/sections; artifacts stay append-only elsewhere.
            if "headline" in payload:
                dashboard["headline"] = str(payload.get("headline") or "").strip()[:200]
            if "actions" in payload:
                dashboard["actions"] = _clean_object_list(payload["actions"], field="actions")
            if "inboxes" in payload:
                dashboard["inboxes"] = _clean_object_list(payload["inboxes"], field="inboxes")
            if "widgets" in payload:
                dashboard["widgets"] = _clean_object_list(payload["widgets"], field="widgets")
            if "tabs" in payload:
                dashboard["tabs"] = _clean_object_list(payload["tabs"], field="tabs")
            if "sheets" in payload:
                dashboard["sheets"] = _clean_object_list(payload["sheets"], field="sheets")
            job["updated_at"] = utc_now_iso()
            self._append_activity(
                job,
                kind="dashboard_updated",
                state="complete",
                summary="Dashboard customized",
            )
            return dashboard

        return self._mutate(operation)

    def add_job_artifact(self, app_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        title = clean_text(payload.get("title"), field="title", required=True, max_length=240)
        kind = require_safe_id(payload.get("kind") or "artifact", field="kind")
        reference = clean_artifact_reference(payload.get("reference"))

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            artifact = {
                "id": new_id("artifact"),
                "title": title,
                "kind": kind,
                "reference": reference,
                "metadata": clean_json_object(payload.get("metadata"), field="metadata"),
                "created_at": utc_now_iso(),
            }
            job["dashboard"]["artifacts"].append(artifact)
            job["updated_at"] = artifact["created_at"]
            self._append_activity(
                job,
                kind="artifact_created",
                state="complete",
                summary=f"Created result: {title}",
                details={"artifact_id": artifact["id"], "kind": kind},
            )
            return artifact

        return self._mutate(operation)
