from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thomas.work import WorkConflictError, WorkCorruptStateError, WorkStore, WorkValidationError


def _job(store: WorkStore) -> tuple[dict[str, Any], dict[str, Any]]:
    app = store.create_app({"id": "dispatch", "name": "Dispatch", "goal": "Keep freight moving"})
    job = store.create_job(
        app["id"],
        {"id": "coordinator", "name": "Coordinator", "goal": "Coordinate daily dispatch"},
    )
    return app, job


def test_job_workflows_are_typed_selected_and_durable(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app, job = _job(store)
    history_id = job["history"]["session_id"]

    intake = store.create_workflow(
        app["id"],
        job["id"],
        {
            "id": "intake",
            "name": "Load intake",
            "purpose": "Turn new load emails into reviewed load records",
            "type": "event",
            "connector_suggestions": ["gmail"],
            "success_criteria": ["Every load has pickup and delivery details"],
        },
    )
    tracking = store.create_workflow(
        app["id"],
        job["id"],
        {
            "id": "tracking",
            "name": "In-transit tracking",
            "purpose": "Find exceptions before they become late deliveries",
            "type": "scheduled",
            "connector_suggestions": ["gmail", "google_drive"],
        },
    )

    assert intake["status"] == "configuring"
    assert tracking["status"] == "planned"
    assert store.active_workflow_id(app["id"], job["id"]) == "intake"
    assert store.get_job(app["id"], job["id"])["connector_bindings"] == []
    with pytest.raises(WorkConflictError, match="select the workflow"):
        store.update_workflow(app["id"], job["id"], "tracking", {"status": "active"})

    selected = store.select_workflow(app["id"], job["id"], "tracking")
    active = store.update_workflow(
        app["id"],
        job["id"],
        selected["id"],
        {"status": "active", "learning": {"summary": "Call the carrier before escalating"}},
    )
    assert active["status"] == "active"
    assert {row["id"]: row["status"] for row in store.list_workflows(app["id"], job["id"])} == {
        "intake": "planned",
        "tracking": "active",
    }
    with pytest.raises(WorkConflictError, match="select another workflow"):
        store.update_workflow(app["id"], job["id"], "tracking", {"status": "completed"})

    reloaded = WorkStore(tmp_path)
    persisted = reloaded.get_job(app["id"], job["id"])
    assert persisted["history"]["session_id"] == history_id
    assert persisted["memory"]["metadata"]["active_workflow_id"] == "tracking"
    assert persisted["memory"]["workflows"][1]["learning"]["summary"].startswith("Call the carrier")

    with pytest.raises(WorkValidationError, match="not installed"):
        store.create_workflow(
            app["id"],
            job["id"],
            {
                "id": "unknown-connector",
                "name": "Unknown connector",
                "purpose": "Prove suggestions stay honest",
                "connector_suggestions": ["imaginary_mail"],
            },
        )


def test_legacy_workflow_memory_is_upgraded_without_client_owned_selection(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app, job = _job(store)

    memory = store.update_job_memory(
        app["id"],
        job["id"],
        {"workflows": [{"step": "Review tender"}, {"name": "Book carrier", "goal": "Book a carrier"}]},
    )

    assert memory["workflows"][0]["status"] == "configuring"
    assert memory["workflows"][1]["status"] == "planned"
    assert memory["metadata"]["active_workflow_id"] == memory["workflows"][0]["id"]
    with pytest.raises(WorkValidationError, match="server-owned"):
        store.update_job_memory(
            app["id"],
            job["id"],
            {"metadata": {"active_workflow_id": memory["workflows"][1]["id"]}},
        )


def test_workflow_store_fails_closed_when_more_than_one_flow_has_focus(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app, job = _job(store)
    for workflow_id in ("first", "second"):
        store.create_workflow(
            app["id"],
            job["id"],
            {"id": workflow_id, "name": workflow_id.title(), "purpose": f"Run {workflow_id}"},
        )
    state = store.snapshot()
    workflows = state["apps"][app["id"]]["jobs"][job["id"]]["memory"]["workflows"]
    workflows[1]["status"] = "active"
    store.state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(WorkCorruptStateError, match="workflow focus"):
        WorkStore(tmp_path)
    workflows[1] = "not-a-workflow"
    store.state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(WorkCorruptStateError, match="workflow entries"):
        WorkStore(tmp_path)


def test_canonical_workflow_container_corruption_is_not_repaired_as_legacy(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app, job = _job(store)
    store.create_workflow(
        app["id"],
        job["id"],
        {"id": "canonical", "name": "Canonical", "purpose": "Prove canonical corruption fails closed"},
    )
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    memory = state["apps"][app["id"]]["jobs"][job["id"]]["memory"]
    assert "active_workflow_id" in memory["metadata"]
    memory["workflows"] = {"corrupt": True}
    store.state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(WorkCorruptStateError, match="job memory"):
        WorkStore(tmp_path)


def test_canonical_workflow_metadata_corruption_is_not_repaired_as_legacy(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app, job = _job(store)
    store.create_workflow(
        app["id"],
        job["id"],
        {"id": "canonical", "name": "Canonical", "purpose": "Preserve canonical metadata"},
    )
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    state["apps"][app["id"]]["jobs"][job["id"]]["memory"]["metadata"] = {}
    store.state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(WorkCorruptStateError, match="workflow focus"):
        WorkStore(tmp_path)


def test_canonical_job_memory_object_corruption_is_not_replaced(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app, job = _job(store)
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    state["apps"][app["id"]]["jobs"][job["id"]]["memory"] = "corrupt"
    store.state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(WorkCorruptStateError, match="job memory"):
        WorkStore(tmp_path)


def test_onboarding_job_creation_is_idempotent_for_the_same_session(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app = store.create_app({"id": "mail", "name": "Mail", "goal": "Run support mail"})
    payload = {
        "name": "Support mail",
        "goal": "Keep customer escalations moving",
        "history_session_id": "session-123",
        "idempotency_key": "session-123",
    }

    first = store.create_job(app["id"], payload)
    updated = store.update_job(app["id"], first["id"], {"metadata": {"owner": "support"}})
    second = store.create_job(app["id"], payload)

    assert updated["metadata"] == {"owner": "support", "onboarding_key": "session-123"}
    assert second["id"] == first["id"]
    assert len(store.list_jobs(app["id"])) == 1
    with pytest.raises(WorkValidationError, match="server-owned"):
        store.update_job(app["id"], first["id"], {"metadata": {"onboarding_key": "replacement"}})
    with pytest.raises(WorkConflictError, match="another session"):
        store.create_job(app["id"], {**payload, "history_session_id": "session-else"})


def test_workflow_aware_onboarding_cannot_skip_goal_and_mapping_phases(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app = store.create_app({"id": "freight", "name": "Freight", "goal": ""})

    assert app["onboarding"]["phase"] == "goal_discovery"
    with pytest.raises(WorkConflictError, match="map workflows"):
        store.update_onboarding(app["id"], {"state": "ready"})
    with pytest.raises(WorkConflictError, match="define the goal"):
        store.update_onboarding(app["id"], {"phase": "workflow_configuration"})
    with pytest.raises(WorkConflictError, match="confirmed goal"):
        store.update_onboarding(app["id"], {"phase": "workflow_mapping"})
    mapped = store.update_onboarding(
        app["id"],
        {
            "phase": "workflow_mapping",
            "fields": {"session_id": "session-123", "confirmed_goal": "Keep customer mail moving"},
        },
    )
    assert mapped["phase"] == "workflow_mapping"
    with pytest.raises(WorkConflictError, match="explicit workflow selection"):
        store.update_onboarding(app["id"], {"phase": "workflow_configuration"})
    configured = store.update_onboarding(
        app["id"],
        {
            "phase": "workflow_configuration",
            "fields": {"workflow_count": 3, "selected_workflow": "Escalation triage"},
        },
    )
    assert configured["phase"] == "workflow_configuration"
    assert configured["fields"]["session_id"] == "session-123"
    with pytest.raises(WorkConflictError, match="four user answers"):
        store.update_onboarding(
            app["id"],
            {"state": "ready", "fields": {"selected_workflow_configured": True}},
        )


def test_workflow_automation_links_are_existing_unique_and_type_compatible(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app, job = _job(store)
    scheduled = store.create_workflow(
        app["id"],
        job["id"],
        {"id": "scheduled", "name": "Scheduled", "purpose": "Send a daily brief", "type": "scheduled"},
    )
    event = store.create_workflow(
        app["id"],
        job["id"],
        {"id": "event", "name": "Event", "purpose": "Handle escalations", "type": "event"},
    )
    with pytest.raises(WorkConflictError, match="must exist"):
        store.update_workflow(app["id"], job["id"], scheduled["id"], {"automation_id": "missing"})
    automation = store.create_automation(
        app["id"],
        job["id"],
        {"id": "daily", "name": "Daily", "trigger": {"type": "daily", "at": "08:30"}},
    )
    store.update_workflow(
        app["id"],
        job["id"],
        scheduled["id"],
        {"automation_id": automation["id"]},
    )
    with pytest.raises(WorkConflictError, match="event workflow"):
        store.update_workflow(app["id"], job["id"], event["id"], {"automation_id": automation["id"]})
    second_scheduled = store.create_workflow(
        app["id"],
        job["id"],
        {"id": "scheduled-two", "name": "Scheduled two", "purpose": "Send another brief", "type": "scheduled"},
    )
    with pytest.raises(WorkConflictError, match="already linked"):
        store.update_workflow(
            app["id"],
            job["id"],
            second_scheduled["id"],
            {"automation_id": automation["id"]},
        )
    with pytest.raises(WorkConflictError, match="linked workflow"):
        store.delete_automation(app["id"], job["id"], automation["id"])
    with pytest.raises(WorkConflictError, match="scheduled workflow"):
        store.update_automation(
            app["id"],
            job["id"],
            automation["id"],
            {"trigger": {"type": "event", "event_name": "urgent"}},
        )


def test_persisted_duplicate_automation_identity_fails_closed(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app, job = _job(store)
    automation = store.create_automation(
        app["id"],
        job["id"],
        {"id": "daily", "name": "Daily", "trigger": {"type": "daily", "at": "08:30"}},
    )
    workflow = store.create_workflow(
        app["id"],
        job["id"],
        {"id": "brief", "name": "Brief", "purpose": "Send the daily brief", "type": "scheduled"},
    )
    store.update_workflow(
        app["id"],
        job["id"],
        workflow["id"],
        {"automation_id": automation["id"]},
    )
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    rows = state["apps"][app["id"]]["jobs"][job["id"]]["automations"]
    rows.append(dict(rows[0]))
    store.state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(WorkCorruptStateError, match="automation ids"):
        WorkStore(tmp_path)
