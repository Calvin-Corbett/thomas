from __future__ import annotations

import pytest

from thomas.work import WorkConflictError, WorkValidationError
from thomas.work.mission import build_mission_job_payload


def _rows(trigger: dict, **template):
    app = {"id": "dispatch", "name": "Dispatch", "status": "active"}
    job = {
        "id": "brief",
        "name": "Brief",
        "goal": "Prepare the brief",
        "status": "active",
        "history": {"session_id": "work:dispatch:brief"},
        "settings": {},
    }
    automation = {
        "id": "automation",
        "name": "Automation",
        "enabled": True,
        "trigger": trigger,
        "mission_template": template,
    }
    return app, job, automation


@pytest.mark.parametrize(
    ("trigger", "expected"),
    [
        ({"type": "manual"}, {}),
        ({"type": "event", "event_name": "gmail.message_received".replace(".", "_")}, {}),
        ({"type": "once", "run_at": "2026-07-15T13:00:00Z"}, {"run_at": "2026-07-15T13:00:00Z"}),
        ({"type": "interval", "every_seconds": 900}, {"schedule": {"type": "interval", "every_seconds": 900}}),
        (
            {"type": "weekly", "at": "08:30", "tz": "America/Chicago", "dow": [5, 1, 1]},
            {"schedule": {"type": "weekly", "at": "08:30", "tz": "America/Chicago", "dow": [1, 5]}},
        ),
    ],
)
def test_mission_payload_supports_work_automation_triggers(trigger: dict, expected: dict) -> None:
    payload = build_mission_job_payload(*_rows(trigger))

    for key, value in expected.items():
        assert payload[key] == value
    assert payload["payload"]["work_history_session_id"] == "work:dispatch:brief"
    assert payload["kind"] == "workflow_task"


@pytest.mark.parametrize(
    "template",
    [
        {"risk_class": "unsafe"},
        {"requires_approval": "yes"},
        {"payload": ["not", "an", "object"]},
    ],
)
def test_mission_payload_rejects_unsafe_template_types(template: dict) -> None:
    with pytest.raises(WorkValidationError):
        build_mission_job_payload(*_rows({"type": "manual"}, **template))


def test_mission_payload_rejects_invalid_time_and_paused_job() -> None:
    with pytest.raises(WorkValidationError, match="valid 24-hour"):
        build_mission_job_payload(*_rows({"type": "daily", "at": "25:70"}))

    app, job, automation = _rows({"type": "manual"})
    job["status"] = "paused"
    with pytest.raises(WorkConflictError, match="must be active"):
        build_mission_job_payload(app, job, automation)


def test_mission_payload_preserves_full_job_ai_settings() -> None:
    app, job, automation = _rows({"type": "manual"})
    job["settings"] = {
        "profile": "openai_codex",
        "model_id": "gpt-5.6-terra",
        "reasoning_effort": "xhigh",
        "autonomy": 4,
        "file_access": "project",
        "memory": False,
        "guardrails": "fortress",
        "token_economy": "max",
    }

    payload = build_mission_job_payload(app, job, automation)

    assert payload["profile"] == "openai_codex"
    assert payload["model_id"] == "gpt-5.6-terra"
    assert payload["payload"]["settings"] == job["settings"]


def test_event_mission_payload_preserves_event_identity() -> None:
    payload = build_mission_job_payload(*_rows({"type": "event", "event_name": "gmail_message_received"}))

    assert payload["payload"]["work_event_name"] == "gmail_message_received"


def test_mission_payload_includes_only_active_job_private_skills() -> None:
    app, job, automation = _rows({"type": "manual"})
    job["private_skills"] = [
        {"id": "vip", "name": "VIP first", "description": "Prioritize owner", "status": "active"},
        {"id": "old", "name": "Old flow", "description": "Disabled", "status": "disabled"},
    ]

    payload = build_mission_job_payload(app, job, automation)

    assert payload["payload"]["private_skills"] == [
        {"id": "vip", "name": "VIP first", "description": "Prioritize owner", "skill_ref": ""}
    ]


def test_mission_payload_includes_only_the_selected_jobs_memory() -> None:
    app, job, automation = _rows({"type": "manual"})
    job["memory"] = {
        "scope": "work/dispatch/brief",
        "summary": "Use the owner-approved morning sequence",
        "workflows": [{"step": "Review VIP messages"}],
        "metadata": {},
    }

    payload = build_mission_job_payload(app, job, automation)

    assert payload["payload"]["job_memory"] == job["memory"]


def test_mission_payload_includes_only_enabled_connector_assignments() -> None:
    app, job, automation = _rows({"type": "manual"})
    job["connector_bindings"] = [
        {
            "id": "binding-ops",
            "account_id": "gmail-ops",
            "provider": "gmail",
            "label": "Operations Gmail",
            "identity": "ops@example.com",
            "credential_ref": "secret:gmail-ops",
            "scopes": ["mail.read"],
            "outbound_approved": False,
            "enabled": True,
        },
        {"id": "binding-off", "account_id": "gmail-off", "provider": "gmail", "enabled": False},
    ]

    payload = build_mission_job_payload(app, job, automation)

    assert payload["payload"]["connector_bindings"] == [
        {
            "binding_id": "binding-ops",
            "account_id": "gmail-ops",
            "provider": "gmail",
            "label": "Operations Gmail",
            "identity": "ops@example.com",
            "scopes": ["mail.read"],
            "outbound_approved": False,
        }
    ]
