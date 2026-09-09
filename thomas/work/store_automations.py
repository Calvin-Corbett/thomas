"""Automation lifecycle, approvals, Mission reconciliation, and event receipts."""

from __future__ import annotations

from typing import Any

from .mission import validate_automation_trigger
from .store_common import _clean_bool
from .store_workflows import validate_workflow_automation_link
from .validation import (
    WorkConflictError,
    WorkCorruptStateError,
    WorkNotFoundError,
    WorkValidationError,
    clean_json_object,
    clean_public_error,
    clean_text,
    new_id,
    require_safe_id,
    utc_now_iso,
)


def validate_automation_definitions(job: dict[str, Any]) -> None:
    """Validate durable automation identity and structural invariants."""

    rows = job.get("automations")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise WorkCorruptStateError("durable Work automation definitions are invalid")
    ids = [str(row.get("id") or "") for row in rows]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise WorkCorruptStateError("durable Work automation ids are invalid")
    for row in rows:
        try:
            require_safe_id(row.get("id"), field="automation_id")
            trigger = row.get("trigger")
            if not isinstance(trigger, dict):
                raise WorkValidationError("automation trigger is invalid")
            require_safe_id(trigger.get("type") or "", field="trigger.type")
            validate_automation_trigger(trigger)
        except WorkValidationError as exc:
            raise WorkCorruptStateError("durable Work automation definitions are invalid") from exc
        if (
            not str(row.get("name") or "").strip()
            or not isinstance(row.get("enabled"), bool)
            or not isinstance(row.get("mission_template"), dict)
            or not isinstance(row.get("delegation"), dict)
        ):
            raise WorkCorruptStateError("durable Work automation definitions are invalid")
        active_ids = row["delegation"].get("active_mission_job_ids", [])
        if (
            not isinstance(active_ids, list)
            or any(not isinstance(value, str) or not value.strip() for value in active_ids)
            or len(active_ids) != len(set(active_ids))
        ):
            raise WorkCorruptStateError("durable Work automation Mission ids are invalid")
        event_receipts = row["delegation"].get("event_receipts", [])
        if not isinstance(event_receipts, list) or any(
            not isinstance(receipt, dict)
            or not str(receipt.get("event_id") or "").strip()
            or receipt.get("state") not in {"pending", "failed", "delegated"}
            for receipt in event_receipts
        ):
            raise WorkCorruptStateError("durable Work automation event receipts are invalid")
        event_ids = [str(receipt.get("event_id") or "") for receipt in event_receipts]
        if len(event_ids) != len(set(event_ids)) or any(
            receipt.get("state") == "delegated" and not str(receipt.get("mission_job_id") or "").strip()
            for receipt in event_receipts
        ):
            raise WorkCorruptStateError("durable Work automation event receipts are inconsistent")


class WorkAutomationMixin:
    def list_automations(self, app_id: str, job_id: str) -> list[dict[str, Any]]:
        return self.get_job(app_id, job_id)["automations"]

    def create_automation(self, app_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name = clean_text(payload.get("name"), field="name", required=True, max_length=160)
        automation_id = require_safe_id(payload.get("id"), field="id") if payload.get("id") else new_id("automation")
        trigger = clean_json_object(payload.get("trigger"), field="trigger")
        trigger_type = require_safe_id(trigger.get("type") or "manual", field="trigger.type")
        trigger["type"] = trigger_type
        validate_automation_trigger(trigger)
        mission_template = clean_json_object(payload.get("mission_template"), field="mission_template")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            if any(row.get("id") == automation_id for row in job["automations"]):
                raise WorkConflictError("automation id already exists")
            now = utc_now_iso()
            automation = {
                "id": automation_id,
                "name": name,
                "enabled": _clean_bool(payload.get("enabled", True), field="enabled"),
                "trigger": trigger,
                "mission_template": mission_template,
                "delegation": {
                    "state": "not_deployed",
                    "mission_job_id": "",
                    "active_mission_job_ids": [],
                    "event_receipts": [],
                    "updated_at": "",
                },
                "created_at": now,
                "updated_at": now,
            }
            job["automations"].append(automation)
            job["updated_at"] = now
            self._append_activity(
                job,
                kind="automation_created",
                state="complete",
                summary=f"Created automation: {name}",
                details={"automation_id": automation_id, "trigger": trigger},
            )
            return automation

        return self._mutate(operation)

    def claim_automation_submission(self, app_id: str, job_id: str, automation_id: str) -> dict[str, Any]:
        """Atomically reserve one Mission submission for an automation."""

        safe_id = require_safe_id(automation_id, field="automation_id")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            automation = next((row for row in job["automations"] if row.get("id") == safe_id), None)
            if not isinstance(automation, dict):
                raise WorkNotFoundError("automation not found")
            delegation = automation.get("delegation") if isinstance(automation.get("delegation"), dict) else {}
            if delegation.get("state") in {
                "submitting",
                "deployed",
                "queued",
                "running",
                "awaiting_approval",
            }:
                raise WorkConflictError("automation already has a Mission run in progress")
            now = utc_now_iso()
            delegation.update({"state": "submitting", "mission_job_id": "", "updated_at": now})
            automation["delegation"] = delegation
            automation["updated_at"] = now
            job["updated_at"] = now
            self._append_activity(
                job,
                kind="automation_submission",
                state="queued",
                summary=f"Submitting automation: {automation['name']}",
                details={"automation_id": safe_id},
            )
            return automation

        return self._mutate(operation)

    def fail_automation_submission(
        self,
        app_id: str,
        job_id: str,
        automation_id: str,
        *,
        error: str,
    ) -> dict[str, Any]:
        safe_id = require_safe_id(automation_id, field="automation_id")
        public_error = clean_public_error(error)

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            automation = next((row for row in job["automations"] if row.get("id") == safe_id), None)
            if not isinstance(automation, dict):
                raise WorkNotFoundError("automation not found")
            delegation = automation.get("delegation") if isinstance(automation.get("delegation"), dict) else {}
            if delegation.get("state") == "submitting":
                now = utc_now_iso()
                delegation.update({"state": "failed", "error": public_error, "updated_at": now})
                automation["delegation"] = delegation
                automation["updated_at"] = now
                job["updated_at"] = now
            return automation

        return self._mutate(operation)

    def update_automation(
        self, app_id: str, job_id: str, automation_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        safe_id = require_safe_id(automation_id, field="automation_id")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            automation = next((row for row in job["automations"] if row.get("id") == safe_id), None)
            if not isinstance(automation, dict):
                raise WorkNotFoundError("automation not found")
            if "name" in payload:
                automation["name"] = clean_text(payload["name"], field="name", required=True, max_length=160)
            if "enabled" in payload:
                automation["enabled"] = _clean_bool(payload["enabled"], field="enabled")
            if "trigger" in payload:
                trigger = clean_json_object(payload["trigger"], field="trigger")
                trigger["type"] = require_safe_id(trigger.get("type") or "manual", field="trigger.type")
                validate_automation_trigger(trigger)
                automation["trigger"] = trigger
            if "mission_template" in payload:
                automation["mission_template"] = clean_json_object(
                    payload["mission_template"], field="mission_template"
                )
            for workflow in job["memory"]["workflows"]:
                if workflow.get("automation_id") == safe_id:
                    validate_workflow_automation_link(
                        job,
                        workflow_id=str(workflow["id"]),
                        workflow_type=str(workflow["type"]),
                        automation_id=safe_id,
                    )
            now = utc_now_iso()
            if payload:
                automation["delegation"] = {
                    "state": "not_deployed",
                    "mission_job_id": "",
                    "active_mission_job_ids": [],
                    "updated_at": now,
                }
            automation["updated_at"] = now
            job["updated_at"] = automation["updated_at"]
            self._append_activity(
                job,
                kind="automation_updated",
                state="complete",
                summary=f"Updated automation: {automation['name']}",
                details={"automation_id": safe_id, "enabled": automation["enabled"]},
            )
            return automation

        return self._mutate(operation)

    def delete_automation(self, app_id: str, job_id: str, automation_id: str) -> dict[str, Any]:
        safe_id = require_safe_id(automation_id, field="automation_id")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            index = next(
                (position for position, row in enumerate(job["automations"]) if row.get("id") == safe_id),
                None,
            )
            if index is None:
                raise WorkNotFoundError("automation not found")
            if any(row.get("automation_id") == safe_id for row in job["memory"]["workflows"]):
                raise WorkConflictError("linked workflow automation cannot be deleted")
            automation = job["automations"].pop(index)
            now = utc_now_iso()
            job["updated_at"] = now
            self._append_activity(
                job,
                kind="automation_deleted",
                state="complete",
                summary=f"Deleted automation: {automation['name']}",
                details={"automation_id": safe_id},
            )
            return automation

        return self._mutate(operation)

    def reconcile_automation_mission(
        self,
        app_id: str,
        job_id: str,
        automation_id: str,
        mission: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist Mission run state and append activity exactly once per status."""

        safe_id = require_safe_id(automation_id, field="automation_id")
        mission_id = clean_text(mission.get("id"), field="mission.id", required=True, max_length=240)
        mission_status = clean_text(mission.get("status"), field="mission.status", required=True).lower()
        state_map = {
            "queued": "queued",
            "running": "running",
            "awaiting_approval": "awaiting_approval",
            "succeeded": "succeeded",
            "failed": "failed",
            "dead": "failed",
            "cancelled": "cancelled",
        }
        if mission_status not in state_map:
            raise WorkValidationError("Mission returned an unsupported job status")
        reconciled_state = state_map[mission_status]

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            automation = next((row for row in job["automations"] if row.get("id") == safe_id), None)
            if not isinstance(automation, dict):
                raise WorkNotFoundError("automation not found")
            delegation = automation.get("delegation") if isinstance(automation.get("delegation"), dict) else {}
            active_ids = [str(value) for value in delegation.get("active_mission_job_ids", [])]
            expected_ids = set(active_ids)
            for field in ("mission_job_id", "last_mission_job_id"):
                value = str(delegation.get(field) or "").strip()
                if value:
                    expected_ids.add(value)
            if mission_id not in expected_ids:
                raise WorkConflictError("Mission status receipt does not match this automation")
            previous_run = delegation.get("last_run") if isinstance(delegation.get("last_run"), dict) else {}
            previous = (
                str(previous_run.get("status") or "")
                if str(previous_run.get("mission_job_id") or "") == mission_id
                else ""
            )
            now = utc_now_iso()
            delegation["mission_status"] = mission_status
            delegation["updated_at"] = now
            delegation["last_run"] = {
                "mission_job_id": mission_id,
                "status": mission_status,
                "result": clean_json_object(mission.get("result"), field="mission.result"),
                "error": clean_public_error(mission.get("error")),
                "updated_at": clean_text(mission.get("updated_at"), field="mission.updated_at", max_length=80) or now,
            }
            if mission_status in {"succeeded", "failed", "dead", "cancelled"}:
                delegation["active_mission_job_ids"] = [value for value in active_ids if value != mission_id]
            if delegation.get("state") != "armed":
                delegation["state"] = reconciled_state
            automation["delegation"] = delegation
            automation["updated_at"] = now
            job["updated_at"] = now
            if previous != mission_status:
                self._append_activity(
                    job,
                    kind="automation_mission_status",
                    state=reconciled_state,
                    summary=f"{automation['name']}: Mission {mission_status.replace('_', ' ')}",
                    details={
                        "automation_id": safe_id,
                        "mission_job_id": mission_id,
                        "result": delegation["last_run"]["result"],
                        "error": delegation["last_run"]["error"],
                    },
                )
            return automation

        return self._mutate(operation)

    def mark_automation_delegated(
        self,
        app_id: str,
        job_id: str,
        automation_id: str,
        *,
        mission_job_id: str,
    ) -> dict[str, Any]:
        safe_id = require_safe_id(automation_id, field="automation_id")
        mission_id = clean_text(mission_job_id, field="mission_job_id", required=True, max_length=240)

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            automation = next((row for row in job["automations"] if row.get("id") == safe_id), None)
            if not isinstance(automation, dict):
                raise WorkNotFoundError("automation not found")
            now = utc_now_iso()
            automation["delegation"] = {"state": "deployed", "mission_job_id": mission_id, "updated_at": now}
            automation["updated_at"] = now
            job["updated_at"] = now
            self._append_activity(
                job,
                kind="automation_deployed",
                state="running",
                summary=f"Delegated automation: {automation['name']}",
                details={"automation_id": safe_id, "mission_job_id": mission_id},
            )
            return automation

        return self._mutate(operation)

    def arm_event_automation(self, app_id: str, job_id: str, automation_id: str) -> dict[str, Any]:
        safe_id = require_safe_id(automation_id, field="automation_id")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            automation = next((row for row in job["automations"] if row.get("id") == safe_id), None)
            if not isinstance(automation, dict):
                raise WorkNotFoundError("automation not found")
            trigger = automation.get("trigger") if isinstance(automation.get("trigger"), dict) else {}
            if str(trigger.get("type") or "") != "event":
                raise WorkValidationError("only event automations can be armed")
            now = utc_now_iso()
            automation["delegation"] = {
                "state": "armed",
                "mission_job_id": "",
                "last_mission_job_id": "",
                "active_mission_job_ids": [],
                "event_receipts": [],
                "updated_at": now,
            }
            automation["updated_at"] = now
            job["updated_at"] = now
            self._append_activity(
                job,
                kind="automation_armed",
                state="waiting",
                summary=f"Armed event automation: {automation['name']}",
                details={"automation_id": safe_id, "event_name": trigger.get("event_name", "")},
            )
            return automation

        return self._mutate(operation)

    def claim_event_delegation(
        self,
        app_id: str,
        job_id: str,
        automation_id: str,
        *,
        event_id: str,
    ) -> dict[str, Any]:
        """Durably reserve one event delivery before calling Mission."""

        safe_id = require_safe_id(automation_id, field="automation_id")
        delivery_id = clean_text(event_id, field="event_id", required=True, max_length=240)

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            automation = next((row for row in job["automations"] if row.get("id") == safe_id), None)
            if not isinstance(automation, dict):
                raise WorkNotFoundError("automation not found")
            delegation = automation.get("delegation") if isinstance(automation.get("delegation"), dict) else {}
            if delegation.get("state") != "armed":
                raise WorkConflictError("event automation must be armed before receiving events")
            receipts = delegation.setdefault("event_receipts", [])
            existing = next((row for row in receipts if row.get("event_id") == delivery_id), None)
            if isinstance(existing, dict):
                if existing.get("state") == "delegated":
                    return {"claimed": False, "receipt": existing}
                existing.update({"state": "pending", "error": "", "updated_at": utc_now_iso()})
                return {"claimed": True, "receipt": existing}
            receipt = {
                "event_id": delivery_id,
                "state": "pending",
                "mission_job_id": "",
                "error": "",
                "updated_at": utc_now_iso(),
            }
            receipts.append(receipt)
            delegation["event_receipts"] = receipts
            delegation["updated_at"] = receipt["updated_at"]
            automation["delegation"] = delegation
            automation["updated_at"] = receipt["updated_at"]
            job["updated_at"] = receipt["updated_at"]
            return {"claimed": True, "receipt": receipt}

        return self._mutate(operation)

    def fail_event_delegation(
        self,
        app_id: str,
        job_id: str,
        automation_id: str,
        *,
        event_id: str,
        error: str,
    ) -> dict[str, Any]:
        """Mark a pre-submit failure retryable without losing its durable receipt."""

        safe_id = require_safe_id(automation_id, field="automation_id")
        delivery_id = clean_text(event_id, field="event_id", required=True, max_length=240)
        public_error = clean_public_error(error)

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            automation = next((row for row in job["automations"] if row.get("id") == safe_id), None)
            if not isinstance(automation, dict):
                raise WorkNotFoundError("automation not found")
            delegation = automation.get("delegation") if isinstance(automation.get("delegation"), dict) else {}
            receipts = delegation.get("event_receipts") if isinstance(delegation.get("event_receipts"), list) else []
            receipt = next((row for row in receipts if row.get("event_id") == delivery_id), None)
            if not isinstance(receipt, dict) or receipt.get("state") != "pending":
                raise WorkConflictError("event delivery reservation is missing")
            receipt.update({"state": "failed", "error": public_error, "updated_at": utc_now_iso()})
            delegation["updated_at"] = receipt["updated_at"]
            automation["updated_at"] = receipt["updated_at"]
            job["updated_at"] = receipt["updated_at"]
            return receipt

        return self._mutate(operation)

    def record_event_delegation(
        self,
        app_id: str,
        job_id: str,
        automation_id: str,
        *,
        mission_job_id: str,
        event_id: str = "",
    ) -> dict[str, Any]:
        safe_id = require_safe_id(automation_id, field="automation_id")
        mission_id = clean_text(mission_job_id, field="mission_job_id", required=True, max_length=240)

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            automation = next((row for row in job["automations"] if row.get("id") == safe_id), None)
            if not isinstance(automation, dict):
                raise WorkNotFoundError("automation not found")
            delegation = automation.get("delegation") if isinstance(automation.get("delegation"), dict) else {}
            if delegation.get("state") != "armed":
                raise WorkConflictError("event automation must be armed before receiving events")
            now = utc_now_iso()
            if event_id:
                delivery_id = clean_text(event_id, field="event_id", required=True, max_length=240)
                receipts = (
                    delegation.get("event_receipts") if isinstance(delegation.get("event_receipts"), list) else []
                )
                receipt = next((row for row in receipts if row.get("event_id") == delivery_id), None)
                if not isinstance(receipt, dict) or receipt.get("state") != "pending":
                    raise WorkConflictError("event delivery reservation is missing")
                receipt.update(
                    {
                        "state": "delegated",
                        "mission_job_id": mission_id,
                        "error": "",
                        "updated_at": now,
                    }
                )
            active_ids = [str(value) for value in delegation.get("active_mission_job_ids", [])]
            if mission_id not in active_ids:
                active_ids.append(mission_id)
            delegation.update(
                {
                    "last_mission_job_id": mission_id,
                    "active_mission_job_ids": active_ids,
                    "last_event_at": now,
                    "updated_at": now,
                }
            )
            automation["delegation"] = delegation
            automation["updated_at"] = now
            job["updated_at"] = now
            self._append_activity(
                job,
                kind="automation_event",
                state="running",
                summary=f"Event triggered: {automation['name']}",
                details={"automation_id": safe_id, "mission_job_id": mission_id},
            )
            return automation

        return self._mutate(operation)
