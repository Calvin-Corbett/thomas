"""Typed, job-private workflow definitions for Thomas Work."""

from __future__ import annotations

from typing import Any

from .connectors import installed_connector_ids
from .store_common import _clean_object_list
from .store_workflow_model import (
    _FOCUS_STATUSES,
    _TRIGGERS_BY_WORKFLOW_TYPE,
    WORKFLOW_STATUSES,
    WORKFLOW_TYPES,
    normalize_workflow_memory,
    validate_workflow_memory,
)
from .validation import (
    WorkConflictError,
    WorkCorruptStateError,
    WorkNotFoundError,
    WorkValidationError,
    clean_json_object,
    clean_string_list,
    clean_text,
    new_id,
    require_safe_id,
    utc_now_iso,
)


def _clean_connector_suggestions(value: Any) -> list[str]:
    suggestions = [item.lower() for item in clean_string_list(value, field="connector_suggestions", limit=16)]
    unavailable = sorted(set(suggestions) - installed_connector_ids())
    if unavailable:
        raise WorkValidationError(f"connector suggestions are not installed: {', '.join(unavailable)}")
    return suggestions


def validate_workflow_automation_link(
    job: dict[str, Any],
    *,
    workflow_id: str,
    workflow_type: str,
    automation_id: str,
) -> None:
    """Require one existing, type-compatible automation per linked workflow."""

    if not automation_id:
        return
    automation = next((row for row in job["automations"] if row.get("id") == automation_id), None)
    if not isinstance(automation, dict):
        raise WorkConflictError("workflow automation must exist in the same job")
    trigger = automation.get("trigger") if isinstance(automation.get("trigger"), dict) else {}
    trigger_type = str(trigger.get("type") or "")
    if trigger_type not in _TRIGGERS_BY_WORKFLOW_TYPE[workflow_type]:
        raise WorkConflictError(f"{workflow_type} workflow cannot use a {trigger_type or 'missing'} trigger")
    if any(
        row.get("id") != workflow_id and row.get("automation_id") == automation_id for row in job["memory"]["workflows"]
    ):
        raise WorkConflictError("automation is already linked to another workflow")


def validate_workflow_automation_links(job: dict[str, Any]) -> None:
    """Fail closed when persisted workflow links are dangling or ambiguous."""

    try:
        for workflow in job["memory"]["workflows"]:
            validate_workflow_automation_link(
                job,
                workflow_id=str(workflow["id"]),
                workflow_type=str(workflow["type"]),
                automation_id=str(workflow["automation_id"]),
            )
    except (KeyError, TypeError, WorkConflictError) as exc:
        raise WorkCorruptStateError("durable Work workflow automation links are invalid") from exc


class WorkWorkflowMixin:
    def list_workflows(self, app_id: str, job_id: str) -> list[dict[str, Any]]:
        return self.get_job(app_id, job_id)["memory"]["workflows"]

    def get_workflow(self, app_id: str, job_id: str, workflow_id: str) -> dict[str, Any]:
        safe_id = require_safe_id(workflow_id, field="workflow_id")
        workflow = next((row for row in self.list_workflows(app_id, job_id) if row.get("id") == safe_id), None)
        if not isinstance(workflow, dict):
            raise WorkNotFoundError("work workflow not found")
        return workflow

    def active_workflow_id(self, app_id: str, job_id: str) -> str:
        return str(self.get_job(app_id, job_id)["memory"]["metadata"].get("active_workflow_id") or "")

    def create_workflow(self, app_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name = clean_text(payload.get("name"), field="name", required=True, max_length=160)
        purpose = clean_text(payload.get("purpose"), field="purpose", required=True, max_length=4_000)
        workflow_id = require_safe_id(payload.get("id"), field="id") if payload.get("id") else new_id("workflow")
        workflow_type = clean_text(payload.get("type") or "manual", field="type").lower()
        if workflow_type not in WORKFLOW_TYPES:
            raise WorkValidationError("workflow type must be manual, scheduled, or event")
        automation_id = clean_text(payload.get("automation_id"), field="automation_id", max_length=80).lower()
        if automation_id:
            automation_id = require_safe_id(automation_id, field="automation_id")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            rows = job["memory"]["workflows"]
            if any(row.get("id") == workflow_id for row in rows):
                raise WorkConflictError("work workflow id already exists")
            validate_workflow_automation_link(
                job,
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                automation_id=automation_id,
            )
            now = utc_now_iso()
            workflow = {
                "id": workflow_id,
                "name": name,
                "purpose": purpose,
                "type": workflow_type,
                "status": "configuring" if not rows else "planned",
                "steps": _clean_object_list(payload.get("steps"), field="steps"),
                "success_criteria": clean_string_list(payload.get("success_criteria"), field="success_criteria"),
                "connector_suggestions": _clean_connector_suggestions(payload.get("connector_suggestions")),
                "automation_id": automation_id,
                "learning": clean_json_object(payload.get("learning"), field="learning"),
                "created_at": now,
                "updated_at": now,
            }
            rows.append(workflow)
            if len(rows) == 1:
                job["memory"]["metadata"]["active_workflow_id"] = workflow_id
            job["updated_at"] = now
            self._append_activity(
                job,
                kind="workflow_created",
                state="complete",
                summary=f"Created workflow: {name}",
                details={"workflow_id": workflow_id},
            )
            return workflow

        return self._mutate(operation)

    def select_workflow(self, app_id: str, job_id: str, workflow_id: str) -> dict[str, Any]:
        safe_id = require_safe_id(workflow_id, field="workflow_id")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            selected = next((row for row in job["memory"]["workflows"] if row.get("id") == safe_id), None)
            if not isinstance(selected, dict) or selected.get("status") == "archived":
                raise WorkNotFoundError("active work workflow not found")
            for row in job["memory"]["workflows"]:
                if row is not selected and row.get("status") in _FOCUS_STATUSES:
                    row["status"] = "planned"
                    row["updated_at"] = utc_now_iso()
            if selected.get("status") not in _FOCUS_STATUSES:
                selected["status"] = "configuring"
            selected["updated_at"] = utc_now_iso()
            job["memory"]["metadata"]["active_workflow_id"] = safe_id
            job["updated_at"] = selected["updated_at"]
            self._append_activity(
                job,
                kind="workflow_selected",
                state="complete",
                summary=f"Selected workflow: {selected['name']}",
                details={"workflow_id": safe_id},
            )
            return selected

        return self._mutate(operation)

    def update_workflow(self, app_id: str, job_id: str, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        safe_id = require_safe_id(workflow_id, field="workflow_id")

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            job = self._job(state, app_id, job_id)
            workflow = next((row for row in job["memory"]["workflows"] if row.get("id") == safe_id), None)
            if not isinstance(workflow, dict):
                raise WorkNotFoundError("work workflow not found")
            selected = job["memory"]["metadata"].get("active_workflow_id") == safe_id
            if "status" in payload:
                status = clean_text(payload["status"], field="status", required=True).lower()
                if status not in WORKFLOW_STATUSES:
                    raise WorkValidationError("workflow status is invalid")
                if status in _FOCUS_STATUSES and not selected:
                    raise WorkConflictError("select the workflow before configuring or activating it")
                if status not in _FOCUS_STATUSES and selected:
                    raise WorkConflictError("select another workflow before completing or archiving this one")
                workflow["status"] = status
            for field, limit in (("name", 160), ("purpose", 4_000)):
                if field in payload:
                    workflow[field] = clean_text(payload[field], field=field, required=True, max_length=limit)
            if "type" in payload:
                workflow_type = clean_text(payload["type"], field="type", required=True).lower()
                if workflow_type not in WORKFLOW_TYPES:
                    raise WorkValidationError("workflow type must be manual, scheduled, or event")
                workflow["type"] = workflow_type
            if "steps" in payload:
                workflow["steps"] = _clean_object_list(payload["steps"], field="steps")
            if "success_criteria" in payload:
                workflow["success_criteria"] = clean_string_list(payload["success_criteria"], field="success_criteria")
            if "connector_suggestions" in payload:
                workflow["connector_suggestions"] = _clean_connector_suggestions(payload["connector_suggestions"])
            if "automation_id" in payload:
                raw_id = clean_text(payload["automation_id"], field="automation_id", max_length=80).lower()
                workflow["automation_id"] = require_safe_id(raw_id, field="automation_id") if raw_id else ""
            validate_workflow_automation_link(
                job,
                workflow_id=safe_id,
                workflow_type=str(workflow["type"]),
                automation_id=str(workflow["automation_id"]),
            )
            if "learning" in payload:
                workflow["learning"] = clean_json_object(payload["learning"], field="learning")
            workflow["updated_at"] = utc_now_iso()
            job["updated_at"] = workflow["updated_at"]
            self._append_activity(
                job,
                kind="workflow_updated",
                state="complete",
                summary=f"Updated workflow: {workflow['name']}",
                details={"workflow_id": safe_id, "status": workflow["status"]},
            )
            return workflow

        return self._mutate(operation)
