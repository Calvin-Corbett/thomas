from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.agent.skills_runtime import discover_runtime_skills
from thomas.work import WorkConflictError, WorkCorruptStateError, WorkStore, WorkValidationError


def test_work_store_persists_job_scoped_resources_and_lifecycle(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app = store.create_app({"id": "dispatch", "name": "Dispatch", "goal": "Run dispatch operations"})
    store.append_onboarding_message(app["id"], {"role": "user", "text": "Keep Midwest loads moving"})
    store.append_onboarding_message(app["id"], {"role": "thomas", "text": "Which lanes matter most?"})
    store.append_onboarding_message(app["id"], {"role": "user", "text": "Chicago to Detroit first"})
    store.update_onboarding(app["id"], {"state": "ready", "fields": {"lanes": ["midwest"]}})

    gmail_primary = store.create_account(
        {
            "id": "gmail-primary",
            "provider": "gmail",
            "label": "Operations inbox",
            "identity": "ops@example.com",
            "credential_ref": "secret:gmail-primary",
        }
    )
    gmail_billing = store.create_account(
        {
            "id": "gmail-billing",
            "provider": "gmail",
            "label": "Billing inbox",
            "identity": "billing@example.com",
            "credential_ref": "secret:gmail-billing",
        }
    )
    jobs = [
        store.create_job(app["id"], {"id": "loads", "name": "Load monitor", "goal": "Monitor loads"}),
        store.create_job(app["id"], {"id": "billing", "name": "Billing", "goal": "Prepare invoices"}),
    ]
    store.bind_account(app["id"], jobs[0]["id"], {"account_id": gmail_primary["id"], "scopes": ["mail.read"]})
    store.bind_account(app["id"], jobs[0]["id"], {"account_id": gmail_billing["id"], "scopes": ["mail.read"]})
    store.bind_account(app["id"], jobs[1]["id"], {"account_id": gmail_primary["id"], "scopes": ["mail.read"]})

    history = store.update_history(
        app["id"],
        jobs[0]["id"],
        {"message_count": 7, "title": "Tuesday load review", "metadata": {"channel": "work"}},
    )
    with pytest.raises(WorkValidationError, match="server-owned"):
        store.update_history(app["id"], jobs[0]["id"], {"session_id": "attacker-controlled"})
    assert history["session_id"] == "work:dispatch:loads"

    store.update_job_dashboard(
        app["id"],
        jobs[0]["id"],
        {"metrics": [{"id": "open-loads", "value": 4}], "sections": [{"id": "exceptions"}]},
    )
    artifact = store.add_job_artifact(
        app["id"],
        jobs[0]["id"],
        {"title": "Load report", "kind": "pdf", "reference": "artifacts/load-report.pdf"},
    )
    skill = store.create_skill(
        app["id"],
        jobs[0]["id"],
        {"id": "carrier-review", "name": "Carrier review", "skill_ref": "skills/carrier-review"},
    )
    assert skill["scope"] == "job_private"
    promoted = store.request_skill_promotion(app["id"], jobs[0]["id"], skill["id"])
    assert promoted["promotion"]["state"] == "requested"

    assert store.set_job_status(app["id"], jobs[0]["id"], "paused")["status"] == "paused"
    assert store.set_job_status(app["id"], jobs[0]["id"], "active")["status"] == "active"
    assert store.set_job_status(app["id"], jobs[1]["id"], "archived")["status"] == "archived"
    with pytest.raises(WorkConflictError, match="cannot be resumed"):
        store.set_job_status(app["id"], jobs[1]["id"], "active")

    reloaded = WorkStore(tmp_path)
    load_job = reloaded.get_job(app["id"], jobs[0]["id"])
    assert load_job["history"]["session_id"] == "work:dispatch:loads"
    assert load_job["history"]["message_count"] == 7
    assert {row["account_id"] for row in load_job["connector_bindings"]} == {
        "gmail-primary",
        "gmail-billing",
    }
    bound_identities = {row["account"]["identity"] for row in reloaded.list_bindings("dispatch", "loads")}
    assert bound_identities == {"ops@example.com", "billing@example.com"}
    assert load_job["dashboard"]["artifacts"][0]["id"] == artifact["id"]
    assert len(reloaded.list_accounts(provider="gmail")) == 2
    assert list((tmp_path / ".thomas" / "work").glob("*.tmp")) == []


def test_work_store_fails_closed_on_corrupt_state(tmp_path: Path) -> None:
    state_path = tmp_path / ".thomas" / "work" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"schema_version": 1, "apps": []}), encoding="utf-8")

    with pytest.raises(WorkCorruptStateError):
        WorkStore(tmp_path)


def test_work_store_rejects_active_content_artifacts_and_plaintext_credentials(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app = store.create_app({"id": "safe", "name": "Safe", "goal": "Keep outputs safe"})
    job = store.create_job(app["id"], {"id": "reports", "name": "Reports", "goal": "Build reports"})

    for reference in (
        "javascript:alert(document.domain)",
        "data:text/html,<script>alert(1)</script>",
        "//attacker.example/result",
        "C:\\Users\\owner\\secret.pdf",
        "../private/report.pdf",
        "reports/%2e%2e/private.pdf",
        "reports/%5c%5cevil.pdf",
        "https://user:password@example.com/report.pdf",
    ):
        with pytest.raises(WorkValidationError):
            store.add_job_artifact(app["id"], job["id"], {"title": "Unsafe", "kind": "html", "reference": reference})

    external = store.add_app_artifact(
        app["id"],
        {"title": "Safe report", "kind": "pdf", "reference": "https://reports.example/result.pdf"},
    )
    assert external["reference"] == "https://reports.example/result.pdf"

    for credential_ref in ("ya29.real-token", '{"access_token":"secret"}', "gmail-password"):
        with pytest.raises(WorkValidationError, match="opaque secret"):
            store.create_account(
                {
                    "provider": "gmail",
                    "label": "Unsafe",
                    "identity": "unsafe@example.com",
                    "credential_ref": credential_ref,
                }
            )


def test_work_store_redacts_untrusted_mission_error_details(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app = store.create_app({"id": "ops", "name": "Ops", "goal": "Run operations"})
    job = store.create_job(app["id"], {"id": "daily", "name": "Daily", "goal": "Run daily"})
    store.create_automation(app["id"], job["id"], {"id": "brief", "name": "Brief", "trigger": {"type": "manual"}})
    store.mark_automation_delegated(app["id"], job["id"], "brief", mission_job_id="mission-1")

    automation = store.reconcile_automation_mission(
        app["id"],
        job["id"],
        "brief",
        {
            "id": "mission-1",
            "status": "failed",
            "error": {
                "code": "provider_timeout",
                "message": "sk-secret failed in C:\\Users\\owner\\private.py",
                "traceback": "Traceback (most recent call last): ...",
                "retryable": True,
            },
        },
    )

    error = automation["delegation"]["last_run"]["error"]
    assert error == {
        "code": "provider_timeout",
        "message": "Mission reported a failure.",
        "retryable": True,
    }
    serialized = json.dumps(store.list_activity(app["id"], job["id"]))
    assert "sk-secret" not in serialized and "private.py" not in serialized and "Traceback" not in serialized


def test_private_skill_promotion_is_two_step_durable_and_globally_visible(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app = store.create_app({"id": "mail", "name": "Mail", "goal": "Triage mail"})
    job = store.create_job(app["id"], {"id": "triage", "name": "Triage", "goal": "Triage mail"})
    skill = store.create_skill(
        app["id"],
        job["id"],
        {"id": "vip-routing", "name": "VIP routing", "description": "Route owner mail first"},
    )

    assert store.list_global_skills() == []
    with pytest.raises(WorkConflictError, match="must be requested"):
        store.approve_skill_promotion(app["id"], job["id"], skill["id"], approved_by="owner")
    requested = store.request_skill_promotion(app["id"], job["id"], skill["id"])
    assert requested["scope"] == "job_private"
    assert requested["promotion"]["state"] == "requested"
    approved, global_skill = store.approve_skill_promotion(app["id"], job["id"], skill["id"], approved_by="local_owner")
    assert approved["scope"] == "job_private"
    assert approved["promotion"]["state"] == "approved"
    assert global_skill["scope"] == "global"
    assert global_skill["source"] == {"app_id": "mail", "job_id": "triage", "skill_id": "vip-routing"}
    assert Path(global_skill["skill_file"]).is_file()
    discovered, roots = discover_runtime_skills(object(), cwd=tmp_path)
    assert str(tmp_path / ".thomas" / "skills") in roots
    assert "global-vip-routing" in {row.name for row in discovered}
    assert WorkStore(tmp_path).list_global_skills() == [global_skill]


def test_activity_ledger_records_dashboard_outputs_and_failures(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app = store.create_app({"id": "reports", "name": "Reports", "goal": "Build reports"})
    job = store.create_job(app["id"], {"id": "daily", "name": "Daily", "goal": "Build daily report"})
    store.update_job_dashboard(app["id"], job["id"], {"metrics": [{"label": "Open", "value": 3}]})
    store.add_job_artifact(
        app["id"], job["id"], {"title": "Daily PDF", "kind": "pdf", "reference": "artifacts/daily.pdf"}
    )
    store.record_activity(
        app["id"],
        job["id"],
        kind="automation_failed",
        state_value="failed",
        summary="Automation could not start",
        details={"error": "Mission unavailable"},
    )
    assert [row["type"] for row in store.list_activity(app["id"], job["id"])] == [
        "job_created",
        "dashboard_updated",
        "artifact_created",
        "automation_failed",
    ]


def test_activity_ledger_sanitizes_legacy_string_errors_on_read(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app = store.create_app({"id": "legacy", "name": "Legacy", "goal": "Read old activity safely"})
    job = store.create_job(app["id"], {"id": "daily", "name": "Daily", "goal": "Run daily"})
    store.record_activity(
        app["id"],
        job["id"],
        kind="automation_failed",
        state_value="failed",
        summary="Automation failed",
        details={"error": "sk-secret leaked from C:\\Users\\owner\\private.py"},
    )

    serialized = json.dumps(store.list_activity(app["id"], job["id"]))
    assert "sk-secret" not in serialized
    assert "private.py" not in serialized
    assert '"code": "mission_failed"' in serialized


def test_onboarding_requires_goal_mapping_and_configuration_before_launch(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app = store.create_app({"id": "mail", "name": "Mail", "goal": ""})
    store.append_onboarding_message(app["id"], {"role": "user", "text": "Triage my inbox"})
    store.append_onboarding_message(app["id"], {"role": "thomas", "text": "Who relies on the result?"})
    with pytest.raises(WorkConflictError, match="map workflows"):
        store.update_onboarding(app["id"], {"state": "ready"})
    for user, thomas in (
        ("The support team", "How is success measured?"),
        ("Urgent messages handled in fifteen minutes", "Here is the workflow map. Which flow comes first?"),
        ("Start with customer escalations", "What approval boundary applies to that flow?"),
    ):
        store.append_onboarding_message(app["id"], {"role": "user", "text": user})
        store.append_onboarding_message(app["id"], {"role": "thomas", "text": thomas})
    store.update_onboarding(
        app["id"],
        {"phase": "workflow_mapping", "fields": {"confirmed_goal": "Triage urgent support mail quickly"}},
    )
    store.update_onboarding(
        app["id"],
        {
            "phase": "workflow_configuration",
            "fields": {
                "workflow_count": 3,
                "selected_workflow": "Customer escalations",
                "selected_workflow_configured": True,
                "selected_workflow_user_turn": 4,
            },
        },
    )
    store.append_onboarding_message(app["id"], {"role": "user", "text": "Require owner approval before sending"})
    store.append_onboarding_message(app["id"], {"role": "thomas", "text": "The selected flow is configured."})
    assert store.update_onboarding(app["id"], {"state": "ready"})["state"] == "ready"


def test_job_memory_and_automation_lifecycle_are_isolated_and_durable(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    first = store.create_app({"id": "first", "name": "First", "goal": "First app"})
    second = store.create_app({"id": "second", "name": "Second", "goal": "Second app"})
    for app in (first, second):
        store.create_job(app["id"], {"id": "daily", "name": "Daily", "goal": "Run daily"})
    store.update_job_memory("first", "daily", {"summary": "First-only memory", "workflows": [{"step": "Review"}]})
    assert store.get_job("second", "daily")["memory"]["summary"] == ""
    assert store.get_job("first", "daily")["memory"]["scope"] == "work/first/daily"

    automation = store.create_automation(
        "first", "daily", {"id": "brief", "name": "Brief", "trigger": {"type": "manual"}}
    )
    assert store.update_automation("first", "daily", automation["id"], {"enabled": False})["enabled"] is False
    assert store.delete_automation("first", "daily", automation["id"])["id"] == "brief"
    reloaded = WorkStore(tmp_path)
    assert reloaded.list_automations("first", "daily") == []
    assert reloaded.get_job("first", "daily")["memory"]["summary"] == "First-only memory"
    assert [row["type"] for row in reloaded.list_activity("first", "daily")][-2:] == [
        "automation_updated",
        "automation_deleted",
    ]
