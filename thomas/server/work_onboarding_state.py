"""Schema validation for model-authored Work onboarding state."""

from __future__ import annotations

from typing import Any

_PHASES = {"goal_discovery", "workflow_mapping", "workflow_configuration"}
_WORKFLOW_TYPES = {"manual", "scheduled", "event"}


def _text(value: Any, *, field: str, max_length: int, required: bool = False) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{field} is required")
    if len(result) > max_length:
        raise ValueError(f"{field} is too long")
    return result


def _workflow_id(value: Any) -> str:
    result = _text(value, field="workflow id", max_length=80, required=True)
    if any(not (char.isalnum() or char in "-_") for char in result):
        raise ValueError("workflow id may contain only letters, numbers, hyphens, and underscores")
    return result


def validate_work_onboarding_state(
    *,
    phase: str,
    confirmed_goal: str,
    workflows: Any,
    selected_workflow_id: str,
    selected_workflow_configured: bool,
) -> dict[str, Any]:
    """Validate structured model output without inspecting conversational prose."""

    normalized_phase = str(phase or "").strip().lower()
    if normalized_phase not in _PHASES:
        raise ValueError("invalid Work onboarding phase")

    if not isinstance(workflows, list) or len(workflows) > 6:
        raise ValueError("workflows must be a list with at most six entries")

    normalized_workflows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in workflows:
        if not isinstance(raw, dict):
            raise ValueError("every workflow must be an object")
        workflow_id = _workflow_id(raw.get("id"))
        if workflow_id in seen_ids:
            raise ValueError("workflow ids must be unique")
        seen_ids.add(workflow_id)
        workflow_type = str(raw.get("type") or "").strip().lower()
        if workflow_type not in _WORKFLOW_TYPES:
            raise ValueError("invalid workflow type")
        connectors = raw.get("connector_suggestions")
        if not isinstance(connectors, list):
            raise ValueError("connector_suggestions must be a list")
        normalized_workflows.append(
            {
                "id": workflow_id,
                "name": _text(raw.get("name"), field="workflow name", max_length=80, required=True),
                "purpose": _text(raw.get("purpose"), field="workflow purpose", max_length=280, required=True),
                "type": workflow_type,
                "connector_suggestions": [
                    _text(value, field="connector id", max_length=80, required=True) for value in connectors[:20]
                ],
            }
        )

    selection = _text(selected_workflow_id, field="selected workflow id", max_length=80)
    if selection and selection not in seen_ids:
        raise ValueError("selected_workflow_id must identify a supplied workflow")
    configured = bool(selected_workflow_configured)
    if configured and not selection:
        raise ValueError("a workflow cannot be configured without an explicit selection")

    return {
        "phase": normalized_phase,
        "confirmed_goal": _text(confirmed_goal, field="confirmed goal", max_length=500),
        "workflows": normalized_workflows,
        "selected_workflow_id": selection,
        "selected_workflow_configured": configured,
    }


__all__ = ["validate_work_onboarding_state"]
