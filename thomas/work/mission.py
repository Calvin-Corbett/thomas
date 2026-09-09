"""Mission delegation contract for Work automation definitions.

This module builds the existing Mission API payload. It deliberately does not
schedule or execute anything; callers must submit the payload through Mission.
"""

from __future__ import annotations

from typing import Any

from .validation import WorkConflictError, WorkValidationError, clean_text

_MISSION_TEMPLATE_KEYS = {
    "goal",
    "model_id",
    "payload",
    "profile",
    "requires_approval",
    "risk_class",
    "workflow",
}
_RISK_CLASSES = {"low", "medium", "high", "critical"}


def validate_automation_trigger(trigger: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Validate one trigger and return its Mission schedule representation."""

    trigger_type = str(trigger.get("type") or "manual").strip().lower()
    if trigger_type == "manual":
        return None, ""
    if trigger_type == "event":
        event_name = clean_text(trigger.get("event_name"), field="trigger.event_name", required=True, max_length=120)
        if not event_name.replace("_", "").replace("-", "").isalnum():
            raise WorkValidationError("event trigger names may contain letters, numbers, underscores, and hyphens")
        return None, ""
    if trigger_type == "once":
        run_at = clean_text(trigger.get("run_at"), field="trigger.run_at", required=True, max_length=80)
        return None, run_at
    if trigger_type == "interval":
        seconds = trigger.get("every_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
            raise WorkValidationError("interval trigger requires a positive integer every_seconds")
        return {"type": "interval", "every_seconds": seconds}, ""
    if trigger_type in {"daily", "weekly"}:
        at = clean_text(trigger.get("at"), field="trigger.at", required=True, max_length=5)
        if len(at) != 5 or at[2] != ":" or not at.replace(":", "").isdigit():
            raise WorkValidationError("daily and weekly trigger times must use HH:MM")
        hour, minute = (int(value) for value in at.split(":"))
        if hour > 23 or minute > 59:
            raise WorkValidationError("daily and weekly trigger times must be valid 24-hour times")
        schedule: dict[str, Any] = {
            "type": trigger_type,
            "at": at,
            "tz": clean_text(trigger.get("tz") or "UTC", field="trigger.tz", max_length=100),
        }
        if trigger_type == "weekly":
            dow = trigger.get("dow")
            if not isinstance(dow, list) or not dow:
                raise WorkValidationError("weekly trigger requires dow")
            if any(isinstance(day, bool) or not isinstance(day, int) or day < 0 or day > 6 for day in dow):
                raise WorkValidationError("weekly trigger dow values must be integers from 0 through 6")
            schedule["dow"] = sorted(set(dow))
        return schedule, ""
    raise WorkValidationError("automation trigger must be manual, event, once, interval, daily, or weekly")


def build_mission_job_payload(
    app: dict[str, Any],
    job: dict[str, Any],
    automation: dict[str, Any],
) -> dict[str, Any]:
    """Build a Mission `/api/mission/jobs` payload without executing it."""

    if app.get("status") != "active":
        raise WorkConflictError("work app must be active before automation deployment")
    if job.get("status") != "active":
        raise WorkConflictError("work job must be active before automation deployment")
    if not bool(automation.get("enabled")):
        raise WorkConflictError("automation is disabled")

    template = automation.get("mission_template")
    if not isinstance(template, dict):
        raise WorkValidationError("automation mission_template must be an object")
    unknown = sorted(set(template) - _MISSION_TEMPLATE_KEYS)
    if unknown:
        raise WorkValidationError(f"unsupported mission template fields: {', '.join(unknown)}")

    goal = clean_text(template.get("goal") or job.get("goal"), field="goal", required=True)
    if "payload" in template and not isinstance(template.get("payload"), dict):
        raise WorkValidationError("mission template payload must be an object")
    nested = template.get("payload") if isinstance(template.get("payload"), dict) else {}
    work_payload = dict(nested)
    settings = dict(job.get("settings") or {})
    work_payload.update(
        {
            "goal": goal,
            "prompt": goal,
            "work_app_id": str(app.get("id") or ""),
            "work_job_id": str(job.get("id") or ""),
            "work_automation_id": str(automation.get("id") or ""),
            "work_history_session_id": str(job.get("history", {}).get("session_id") or ""),
            "settings": settings,
            # Private skills are carried only inside this Work job's Mission
            # payload. They are never registered globally unless the owner uses
            # the separate two-step promotion flow.
            "private_skills": [
                {
                    "id": str(skill.get("id") or ""),
                    "name": str(skill.get("name") or ""),
                    "description": str(skill.get("description") or ""),
                    "skill_ref": str(skill.get("skill_ref") or ""),
                }
                for skill in job.get("private_skills") or []
                if isinstance(skill, dict) and skill.get("status") != "disabled"
            ],
            "job_memory": dict(job.get("memory") or {}),
            # Mission receives only public account assignment. The request-scoped
            # connector runtime resolves credentials from the server-owned Work
            # store; SecretStore references never cross into Mission payloads.
            "connector_bindings": [
                {
                    "binding_id": str(binding.get("id") or ""),
                    "account_id": str(binding.get("account_id") or ""),
                    "provider": str(binding.get("provider") or ""),
                    "label": str(binding.get("label") or ""),
                    "identity": str(binding.get("identity") or ""),
                    "scopes": [str(scope) for scope in binding.get("scopes") or []],
                    "outbound_approved": bool(binding.get("outbound_approved", False)),
                }
                for binding in job.get("connector_bindings") or []
                if isinstance(binding, dict) and binding.get("enabled", True)
            ],
        }
    )
    # Mission's Workflow runner consumes execution controls from the top level
    # of its payload, not from the nested settings receipt. Preserve the receipt
    # and also map every dial to the canonical runtime key.
    setting_aliases = {
        "autonomy": "autonomy_level",
        "file_access": "file_access",
        "guardrails": "thomas_guardrails",
        "memory": "memory",
        "model_id": "model_id",
        "profile": "profile",
        "reasoning": "reasoning_effort",
        "reasoning_effort": "reasoning_effort",
        "thinking": "reasoning_effort",
        "tokenEconomy": "token_economy",
        "token_economy": "token_economy",
    }
    for source, target in setting_aliases.items():
        if source in settings and settings[source] is not None:
            work_payload[target] = settings[source]
    risk_class = clean_text(template.get("risk_class") or "low", field="risk_class", max_length=20).lower()
    if risk_class not in _RISK_CLASSES:
        raise WorkValidationError("risk_class must be low, medium, high, or critical")
    workflow = clean_text(
        template.get("workflow") or "orchestrator_worker",
        field="workflow",
        required=True,
        max_length=240,
    )
    requires_approval = template.get("requires_approval", False)
    if not isinstance(requires_approval, bool):
        raise WorkValidationError("requires_approval must be true or false")
    mission: dict[str, Any] = {
        "name": f"{app.get('name')}: {job.get('name')} - {automation.get('name')}",
        "kind": "workflow_task",
        "goal": goal,
        "prompt": goal,
        "workflow": workflow,
        "risk_class": risk_class,
        "requires_approval": requires_approval,
        "session_id": str(job.get("history", {}).get("session_id") or ""),
        "payload": work_payload,
    }
    for field in ("profile", "model_id"):
        value = template.get(field) or job.get("settings", {}).get(field)
        if value:
            mission[field] = clean_text(value, field=field, max_length=240)
    trigger = automation.get("trigger")
    if not isinstance(trigger, dict):
        raise WorkValidationError("automation trigger must be an object")
    schedule, run_at = validate_automation_trigger(trigger)
    if schedule is not None:
        mission["schedule"] = schedule
    if run_at:
        mission["run_at"] = run_at
    if str(trigger.get("type") or "").strip().lower() == "event":
        mission["payload"]["work_event_name"] = str(trigger.get("event_name") or "")
    return mission
