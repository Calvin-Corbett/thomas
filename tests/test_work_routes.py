from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.chat.conversation import ConversationManager
from thomas.chat.session_store import SessionMeta, SessionStore
from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE
from thomas.server.routes.work import APP_WORK_STORE, register_work_routes
from thomas.server.routes.work_connector_runtime import connect_account_secret
from thomas.server.secrets import SecretStore
from thomas.work import WorkDependencyUnavailableError, WorkStore

WORK_UI = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js" / "unified_work_mode.js"
WORK_UI_SUPPORT = WORK_UI.with_name("unified_work_support.js")
CHAT_HTML = WORK_UI.parents[1] / "chat.html"


async def _client(
    root: Path,
    *,
    submitter=None,
    status_provider=None,
    canceller=None,
    store=None,
    session_store=None,
) -> TestClient:
    app = web.Application()
    app[APP_SECRETS] = SecretStore(root / "secrets")
    if session_store is not None:
        app[APP_SESSION_STORE] = session_store
    register_work_routes(
        app,
        require_api_access=lambda request: None,
        store=store or WorkStore(root),
        mission_submitter=submitter,
        mission_status_provider=status_provider,
        mission_canceller=canceller,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def test_connector_reconnect_stages_new_secret_when_account_update_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkStore(tmp_path / "work")
    account = store.create_account(
        {"id": "owner", "provider": "gmail", "label": "Owner", "identity": "owner@example.com"}
    )
    secret_store = SecretStore(tmp_path / "secrets")
    credential_ref = "secret:work/gmail/owner"
    secret_store.set(credential_ref, "old-token", persist=True)
    store.update_account(account["id"], {"credential_ref": credential_ref, "status": "active"})
    app = web.Application()
    app[APP_SECRETS] = secret_store

    def fail_persist(_state: dict[str, Any]) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(store, "_persist", fail_persist)

    with pytest.raises(WorkDependencyUnavailableError):
        connect_account_secret(app, store, account["id"], {"credential": "new-token"})

    assert secret_store.get(credential_ref) == "old-token"
    assert secret_store.is_persisted(credential_ref) is True
    stored_account = next(row for row in store.list_accounts(include_archived=True) if row["id"] == account["id"])
    assert stored_account["credential_ref"] == credential_ref


def test_work_ui_exposes_scoped_memory_readiness_and_automation_controls() -> None:
    text = WORK_UI.read_text(encoding="utf-8") + WORK_UI_SUPPORT.read_text(encoding="utf-8")
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert html.index("unified_work_support.js") < html.index("unified_work_mode.js")
    assert "userTurns >= 4" in text
    assert "state.onboardingPhase === 'workflow_configuration'" in text
    assert "Goal" in text
    assert "Workflow map" in text
    assert "Configure one" in text
    assert "function onboardingWorkflowCandidates()" in text
    assert "function selectedOnboardingWorkflow(candidates)" in text
    assert ".filter(Boolean)" in text
    assert "const ordinals = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth']" in text
    assert "onboardingInstruction(jobName, turn)" in text
    assert "do not discuss tools, connectors, cadence, or execution" in text
    assert "function confirmedOnboardingGoal()" in text
    assert "function onboardingWorkflowDrafts(candidates)" in text
    assert "selected_workflow_id: selected ? state.onboardingWorkflowId : ''" in text
    assert "const savedWorkflowId = String(fields.selected_workflow_id || '')" in text
    assert "state.onboardingWorkflowId = drafts[position].id" in text
    assert "const persistedIndex = drafts.findIndex" in text
    assert "function activeJobDraft(app = state.activeApp)" in text
    assert "async function persistJobDraft(patch)" in text
    assert "const draftSessionId = String(draft.session_id || '')" in text
    assert "`${id}:onboarding:${draftSessionId}`" in text
    assert "fields: { job_draft: {} }" in text
    assert "idempotency_key: state.sessionId" in text
    assert "generation !== selectionGeneration" in text
    assert "controller.signal.aborted" in text
    assert "onDelta: value =>" in text
    assert "data-work-all-jobs" in text
    assert "data-work-card-status" in text
    assert "data-work-card-run" in text
    assert "data-work-workflow-select" in text
    assert "data-work-workflow-activate" in text
    assert "data-work-workflow-run" in text
    assert "data-work-workflow-automation" in text
    assert "request(`${base}/workflows`)" in text
    assert "/run-once`" in text
    assert "private_context" not in text
    assert "contextId: `${state.activeApp.id}:${state.activeJob.id}`" in text
    assert "data-work-automation-edit-open" in text
    assert "data-work-automation-toggle" in text
    assert "data-work-automation-delete" in text
    assert "method: 'DELETE'" in text
    assert "reconcileTimer" in text
    assert "state.formDirty" in text
    assert "form:focus-within" in text
    assert 'role="log" aria-live="polite"' in text
    assert "aria-pressed=\"${selected ? 'true' : 'false'}\"" in text
    assert "scopes: []" not in text
    assert "state.connectors.find(row => row.id === account.provider)" in text
    assert "body: JSON.stringify({ account_id: accountId, scopes: ['read'] })" in text
    assert "function safeArtifactHref(value)" in text
    assert 'rel="noopener noreferrer"' in text
    assert "Unsafe result link blocked" in text
    assert "decodedPath.split('/').includes('..')" in text
    assert "!resolved.username && !resolved.password" in text
    assert "function visibleWorkMessage(message)" in text
    assert "display_prompt: options.displayPrompt || undefined" in text
    assert "|| (chats.chats || [])[0]" not in text
    assert "Thomas returned a malformed stream event." in text
    assert "catch (error) { return; }" not in text
    assert "function onboardingBrief()" in text
    assert "function inferredOnboardingAutomation(job, brief)" not in text
    assert text.count("dow: [0, 1, 2, 3, 4]") == 2
    assert "trigger.dow = [0, 1, 2, 3, 4]" not in text
    assert "[1, 2, 3, 4, 5]" not in text
    assert "async function provisionOnboardedJob(job)" in text
    assert "message_count: state.messages.length" in text
    assert "Private workflow learned from this job onboarding." not in text
    assert "requires_approval:" in text
    assert "queued: 'Queued'" in text
    assert "awaiting_approval: 'Awaiting approval'" in text
    assert ">${deployLabel}</button>" in text
    assert "const setupFailures = await provisionOnboardedJob(data.job)" in text
    assert "account.has_credentials === true" in text
    assert "Connect this account before binding it to a job." in text
    assert "credential_ref" not in text
    assert "/connect`" in text


@pytest.mark.asyncio
async def test_work_job_create_retry_survives_onboarding_context_transfer(tmp_path: Path) -> None:
    session_store = SessionStore(tmp_path / "sessions", auto_save_debounce_ms=0)
    conversation = ConversationManager().append_message("user", "Set up support triage")
    await session_store.save(
        "onboarding-session",
        conversation,
        SessionMeta(
            session_id="onboarding-session",
            surface_mode="work",
            context_id="mail:onboarding:onboarding-session",
        ),
        force=True,
    )
    client = await _client(tmp_path / "work", session_store=session_store)
    try:
        assert (
            await client.post(
                "/api/work/apps",
                json={"id": "mail", "name": "Mail", "goal": "Keep support mail moving"},
            )
        ).status == 201
        payload = {
            "name": "Support triage",
            "goal": "Resolve customer escalations quickly",
            "history_session_id": "onboarding-session",
            "idempotency_key": "onboarding-session",
        }
        first = await client.post("/api/work/apps/mail/jobs", json=payload)
        second = await client.post("/api/work/apps/mail/jobs", json=payload)
        first_body = await first.json()
        second_body = await second.json()

        assert first.status == 201
        assert second.status == 200
        assert second_body["job"]["id"] == first_body["job"]["id"]
        assert len(client.server.app[APP_WORK_STORE].list_jobs("mail")) == 1
        assert (await session_store.load_meta("onboarding-session")).context_id == f"mail:{first_body['job']['id']}"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_concurrent_onboarding_retry_cannot_rollback_another_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_store = SessionStore(tmp_path / "sessions", auto_save_debounce_ms=0)
    conversation = ConversationManager().append_message("user", "Set up support triage")
    await session_store.save(
        "onboarding-session",
        conversation,
        SessionMeta(
            session_id="onboarding-session",
            surface_mode="work",
            context_id="mail:onboarding:onboarding-session",
        ),
        force=True,
    )
    original_save = session_store.save
    first_save_started = asyncio.Event()
    release_first_save = asyncio.Event()
    save_calls = 0

    async def flaky_save(*args: Any, **kwargs: Any) -> bool:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 1:
            first_save_started.set()
            await release_first_save.wait()
            return False
        return await original_save(*args, **kwargs)

    monkeypatch.setattr(session_store, "save", flaky_save)
    client = await _client(tmp_path / "work", session_store=session_store)
    try:
        await client.post(
            "/api/work/apps",
            json={"id": "mail", "name": "Mail", "goal": "Keep support mail moving"},
        )
        payload = {
            "name": "Support triage",
            "goal": "Resolve customer escalations quickly",
            "history_session_id": "onboarding-session",
            "idempotency_key": "onboarding-session",
        }
        first = asyncio.create_task(client.post("/api/work/apps/mail/jobs", json=payload))
        await first_save_started.wait()
        second = asyncio.create_task(client.post("/api/work/apps/mail/jobs", json=payload))
        await asyncio.sleep(0)
        release_first_save.set()
        responses = await asyncio.gather(first, second)

        assert sorted(response.status for response in responses) == [201, 503]
        jobs = client.server.app[APP_WORK_STORE].list_jobs("mail")
        assert len(jobs) == 1
        assert (await session_store.load_meta("onboarding-session")).context_id == f"mail:{jobs[0]['id']}"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_work_routes_redact_secret_references_and_reject_active_content_artifacts(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        await client.post("/api/work/apps", json={"id": "safe", "name": "Safe", "goal": "Safe outputs"})
        await client.post(
            "/api/work/apps/safe/jobs",
            json={"id": "reports", "name": "Reports", "goal": "Build reports"},
        )
        created = await client.post(
            "/api/work/accounts",
            json={
                "id": "gmail-safe",
                "provider": "gmail",
                "label": "Safe inbox",
                "identity": "safe@example.com",
            },
        )
        created_body = await created.json()
        assert created.status == 201
        assert created_body["account"]["has_credentials"] is False
        assert "credential_ref" not in created_body["account"]

        connected = await client.post(
            "/api/work/accounts/gmail-safe/connect",
            json={"credential": "SAFE_TOKEN"},
        )
        assert connected.status == 200
        assert (await connected.json())["account"]["has_credentials"] is True

        listed_body = await (await client.get("/api/work/accounts")).json()
        assert listed_body["accounts"][0]["has_credentials"] is True
        assert "credential_ref" not in listed_body["accounts"][0]

        unsafe = await client.post(
            "/api/work/apps/safe/jobs/reports/artifacts",
            json={"title": "Unsafe", "kind": "html", "reference": "javascript:alert(1)"},
        )
        assert unsafe.status == 400
        assert (await unsafe.json())["code"] == "work_validation_error"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_work_routes_delegate_automation_to_mission(tmp_path: Path) -> None:
    submitted: list[dict[str, Any]] = []

    async def mission_submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(payload)
        return {"job": {"id": "mission-job-123"}}

    async def mission_canceller(job_id: str) -> dict[str, Any]:
        return {"id": job_id, "status": "cancelled"}

    client = await _client(
        tmp_path,
        submitter=mission_submitter,
        canceller=mission_canceller,
    )
    try:
        response = await client.post(
            "/api/work/apps",
            json={"id": "dispatch", "name": "Dispatch", "goal": "Operate dispatch"},
        )
        assert response.status == 201
        assert (await response.json())["app"]["status"] == "active"

        for account in (
            {
                "id": "gmail-ops",
                "provider": "gmail",
                "label": "Operations",
                "identity": "ops@example.com",
            },
            {
                "id": "gmail-owner",
                "provider": "gmail",
                "label": "Owner",
                "identity": "owner@example.com",
            },
        ):
            assert (await client.post("/api/work/accounts", json=account)).status == 201
            assert (
                await client.post(
                    f"/api/work/accounts/{account['id']}/connect",
                    json={"credential": f"TOKEN_{account['id']}"},
                )
            ).status == 200

        response = await client.post(
            "/api/work/apps/dispatch/jobs",
            json={"id": "morning-brief", "name": "Morning brief", "goal": "Prepare the brief"},
        )
        assert response.status == 201
        assert (await response.json())["job"]["history"]["session_id"] == "work:dispatch:morning-brief"
        assert (
            await client.post(
                "/api/work/apps/dispatch/jobs/morning-brief/bindings",
                json={"account_id": "gmail-ops", "scopes": ["mail.read"]},
            )
        ).status == 201
        bindings = await client.get("/api/work/apps/dispatch/jobs/morning-brief/bindings")
        bindings_body = await bindings.json()
        assert bindings_body["bindings"][0]["account"]["identity"] == "ops@example.com"
        response = await client.post(
            "/api/work/apps/dispatch/jobs/morning-brief/automations",
            json={
                "id": "daily-brief",
                "name": "Daily brief",
                "trigger": {"type": "daily", "at": "08:30", "tz": "America/Chicago"},
                "mission_template": {"risk_class": "low", "requires_approval": False},
            },
        )
        assert response.status == 201

        response = await client.post("/api/work/apps/dispatch/jobs/morning-brief/automations/daily-brief/deploy")
        body = await response.json()
        assert response.status == 202
        assert body["mission"] == {"job_id": "mission-job-123", "delegated": True}
        assert body["automation"]["delegation"]["state"] == "deployed"
        assert submitted[0]["schedule"] == {
            "type": "daily",
            "at": "08:30",
            "tz": "America/Chicago",
        }
        assert submitted[0]["payload"]["work_app_id"] == "dispatch"
        assert submitted[0]["payload"]["work_job_id"] == "morning-brief"
        assert submitted[0]["session_id"] == "work:dispatch:morning-brief"
        assert submitted[0]["payload"]["connector_bindings"] == [
            {
                "binding_id": bindings_body["bindings"][0]["id"],
                "account_id": "gmail-ops",
                "provider": "gmail",
                "label": "Operations",
                "identity": "ops@example.com",
                "scopes": ["read"],
                "outbound_approved": False,
            }
        ]

        assert (await client.post("/api/work/apps/dispatch/jobs/morning-brief/pause")).status == 200
        paused = await client.get("/api/work/apps/dispatch/jobs/morning-brief")
        assert (await paused.json())["job"]["status"] == "paused"
        assert (await client.post("/api/work/apps/dispatch/jobs/morning-brief/resume")).status == 200

        unsafe = await client.post(
            "/api/work/apps",
            json={"id": "../escape", "name": "Unsafe", "goal": "No"},
        )
        assert unsafe.status == 400
        assert (await unsafe.json())["code"] == "work_validation_error"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_work_routes_reject_cross_provider_and_unapproved_outbound_scopes(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        await client.post("/api/work/apps", json={"id": "mail", "name": "Mail", "goal": "Read mail"})
        await client.post("/api/work/apps/mail/jobs", json={"id": "triage", "name": "Triage", "goal": "Read mail"})
        await client.post(
            "/api/work/accounts",
            json={"id": "gmail-owner", "provider": "gmail", "label": "Owner", "identity": "owner@example.com"},
        )
        await client.post("/api/work/accounts/gmail-owner/connect", json={"credential": "OWNER_TOKEN"})

        cross_provider = await client.post(
            "/api/work/apps/mail/jobs/triage/bindings",
            json={"account_id": "gmail-owner", "scopes": ["drive.write"], "approve_outbound": True},
        )
        assert cross_provider.status == 400

        unapproved_send = await client.post(
            "/api/work/apps/mail/jobs/triage/bindings",
            json={"account_id": "gmail-owner", "scopes": ["send"]},
        )
        assert unapproved_send.status == 400

        read_only = await client.post(
            "/api/work/apps/mail/jobs/triage/bindings",
            json={"account_id": "gmail-owner"},
        )
        assert read_only.status == 201
        assert (await read_only.json())["binding"]["scopes"] == ["read"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_work_routes_fail_closed_without_mission_submitter(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        await client.post(
            "/api/work/apps",
            json={"id": "dispatch", "name": "Dispatch", "goal": "Operate dispatch"},
        )
        await client.post(
            "/api/work/apps/dispatch/jobs",
            json={"id": "brief", "name": "Brief", "goal": "Prepare brief"},
        )
        await client.post(
            "/api/work/apps/dispatch/jobs/brief/automations",
            json={"id": "manual", "name": "Manual", "trigger": {"type": "manual"}},
        )
        response = await client.post("/api/work/apps/dispatch/jobs/brief/automations/manual/deploy")
        assert response.status == 503
        assert (await response.json())["code"] == "work_dependency_unavailable"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_event_automation_arms_then_delegates_each_matching_event(tmp_path: Path) -> None:
    submitted: list[dict[str, Any]] = []

    async def mission_submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(payload)
        return {"job_id": f"mission-{len(submitted)}"}

    client = await _client(tmp_path, submitter=mission_submitter)
    try:
        await client.post("/api/work/apps", json={"id": "mail", "name": "Mail", "goal": "Triage mail"})
        await client.post(
            "/api/work/apps/mail/jobs",
            json={"id": "triage", "name": "Triage", "goal": "Triage new mail"},
        )
        await client.post(
            "/api/work/apps/mail/jobs/triage/automations",
            json={
                "id": "on-message",
                "name": "On message",
                "trigger": {"type": "event", "event_name": "gmail_message_received"},
            },
        )
        await client.post(
            "/api/work/apps/mail/jobs/triage/workflows",
            json={
                "id": "new-mail",
                "name": "New mail",
                "purpose": "Classify each new customer message",
                "type": "event",
                "automation_id": "on-message",
            },
        )
        await client.patch(
            "/api/work/apps/mail/jobs/triage/workflows/new-mail",
            json={"status": "active"},
        )
        armed = await client.post("/api/work/apps/mail/jobs/triage/automations/on-message/deploy")
        armed_body = await armed.json()
        assert armed.status == 202
        assert armed_body["mission"] == {"armed": True, "event_name": "gmail_message_received"}
        assert submitted == []

        event = await client.post(
            "/api/work/events/gmail_message_received",
            json={"message_id": "msg-42", "account_id": "gmail-owner"},
        )
        event_body = await event.json()
        assert event.status == 202
        assert event_body["delegated"][0]["mission_job_id"] == "mission-1"
        assert event_body["delegated"][0]["state"] == "armed"
        assert submitted[0]["payload"]["event"]["message_id"] == "msg-42"
        assert submitted[0]["payload"]["work_workflow_id"] == "new-mail"
        assert submitted[0]["goal"] == "Classify each new customer message"

        second = await client.post(
            "/api/work/events/gmail_message_received",
            json={"message_id": "msg-43"},
        )
        assert (await second.json())["delegated"][0]["mission_job_id"] == "mission-2"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_skill_promotion_routes_require_request_then_create_global_skill(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        await client.post("/api/work/apps", json={"id": "mail", "name": "Mail", "goal": "Triage mail"})
        await client.post("/api/work/apps/mail/jobs", json={"id": "triage", "name": "Triage", "goal": "Triage mail"})
        created = await client.post(
            "/api/work/apps/mail/jobs/triage/skills",
            json={"id": "vip", "name": "VIP routing", "description": "Route owner first"},
        )
        assert created.status == 201

        premature = await client.post(
            "/api/work/apps/mail/jobs/triage/skills/vip/promotion/approve",
            json={"approved_by": "local_owner"},
        )
        assert premature.status == 409
        assert (await client.get("/api/work/skills")).status == 200

        assert (await client.post("/api/work/apps/mail/jobs/triage/skills/vip/promotion/request")).status == 200
        approved = await client.post(
            "/api/work/apps/mail/jobs/triage/skills/vip/promotion/approve",
            json={"approved_by": "local_owner"},
        )
        body = await approved.json()
        assert approved.status == 200
        assert body["skill"]["promotion"]["state"] == "approved"
        assert body["global_skill"]["scope"] == "global"
        global_rows = await (await client.get("/api/work/skills")).json()
        assert [row["id"] for row in global_rows["skills"]] == ["global-vip"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_automation_routes_reconcile_mission_and_support_full_lifecycle(tmp_path: Path) -> None:
    mission = {
        "id": "mission-brief",
        "status": "queued",
        "result": {},
        "error": {},
        "updated_at": "2026-07-14T12:00:00+00:00",
    }

    async def submitter(_payload: dict[str, Any]) -> dict[str, Any]:
        return {"job_id": mission["id"]}

    async def status_provider(job_id: str) -> dict[str, Any] | None:
        return dict(mission) if job_id == mission["id"] else None

    client = await _client(tmp_path, submitter=submitter, status_provider=status_provider)
    try:
        await client.post("/api/work/apps", json={"id": "reports", "name": "Reports", "goal": "Reports"})
        await client.post(
            "/api/work/apps/reports/jobs",
            json={"id": "daily", "name": "Daily", "goal": "Build the daily report"},
        )
        await client.post(
            "/api/work/apps/reports/jobs/daily/automations",
            json={"id": "brief", "name": "Brief", "trigger": {"type": "manual"}},
        )
        await client.post("/api/work/apps/reports/jobs/daily/automations/brief/deploy")

        listed = await client.get("/api/work/apps/reports/jobs/daily/automations")
        first = await listed.json()
        assert first["mission_available"] is True
        assert first["automations"][0]["delegation"]["state"] == "queued"

        mission.update(
            status="succeeded",
            result={"artifact": "reports/daily.pdf"},
            updated_at="2026-07-14T12:03:00+00:00",
        )
        completed = await client.get("/api/work/apps/reports/jobs/daily/automations")
        completed_row = (await completed.json())["automations"][0]
        assert completed_row["delegation"]["state"] == "succeeded"
        assert completed_row["delegation"]["last_run"]["result"] == {"artifact": "reports/daily.pdf"}
        await client.get("/api/work/apps/reports/jobs/daily/automations")
        activity = await (await client.get("/api/work/apps/reports/jobs/daily/activity")).json()
        statuses = [row for row in activity["activity"] if row["type"] == "automation_mission_status"]
        assert [row["state"] for row in statuses] == ["queued", "succeeded"]

        disabled = await client.patch("/api/work/apps/reports/jobs/daily/automations/brief", json={"enabled": False})
        assert (await disabled.json())["automation"]["enabled"] is False
        deleted = await client.delete("/api/work/apps/reports/jobs/daily/automations/brief")
        assert (await deleted.json())["automation"]["id"] == "brief"
        assert (await (await client.get("/api/work/apps/reports/jobs/daily/automations")).json())["automations"] == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_disabling_or_deleting_deployed_automation_cancels_mission_first(tmp_path: Path) -> None:
    mission_status: dict[str, str] = {}
    cancelled: list[str] = []

    async def submitter(_payload: dict[str, Any]) -> dict[str, Any]:
        mission_id = f"mission-{len(mission_status) + 1}"
        mission_status[mission_id] = "queued"
        return {"job_id": mission_id}

    async def canceller(job_id: str) -> dict[str, Any]:
        cancelled.append(job_id)
        mission_status[job_id] = "cancelled"
        return {"id": job_id, "status": "cancelled"}

    client = await _client(tmp_path, submitter=submitter, canceller=canceller)
    try:
        await client.post("/api/work/apps", json={"id": "ops", "name": "Ops", "goal": "Operate"})
        await client.post(
            "/api/work/apps/ops/jobs",
            json={"id": "daily", "name": "Daily", "goal": "Run daily"},
        )
        for automation_id in ("disable-me", "delete-me"):
            await client.post(
                "/api/work/apps/ops/jobs/daily/automations",
                json={"id": automation_id, "name": automation_id, "trigger": {"type": "manual"}},
            )
            deployed = await client.post(f"/api/work/apps/ops/jobs/daily/automations/{automation_id}/deploy")
            assert deployed.status == 202

        disabled = await client.patch(
            "/api/work/apps/ops/jobs/daily/automations/disable-me",
            json={"enabled": False},
        )
        disabled_body = await disabled.json()
        assert disabled_body["automation"]["delegation"]["state"] == "not_deployed"

        enabled = await client.patch(
            "/api/work/apps/ops/jobs/daily/automations/disable-me",
            json={"enabled": True},
        )
        assert enabled.status == 200
        redeployed = await client.post("/api/work/apps/ops/jobs/daily/automations/disable-me/deploy")
        assert redeployed.status == 202
        assert (await redeployed.json())["mission"]["job_id"] == "mission-3"

        deleted = await client.delete("/api/work/apps/ops/jobs/daily/automations/delete-me")

        assert disabled.status == 200
        assert deleted.status == 200
        assert cancelled == ["mission-1", "mission-2"]
        assert mission_status == {
            "mission-1": "cancelled",
            "mission-2": "cancelled",
            "mission-3": "queued",
        }
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_linked_deployed_automation_delete_is_rejected_before_mission_cancel(tmp_path: Path) -> None:
    cancelled: list[str] = []

    async def submitter(_payload: dict[str, Any]) -> dict[str, Any]:
        return {"job_id": "mission-linked"}

    async def canceller(job_id: str) -> dict[str, Any]:
        cancelled.append(job_id)
        return {"id": job_id, "status": "cancelled"}

    client = await _client(tmp_path, submitter=submitter, canceller=canceller)
    try:
        await client.post("/api/work/apps", json={"id": "ops", "name": "Ops", "goal": "Operate"})
        await client.post(
            "/api/work/apps/ops/jobs",
            json={"id": "daily", "name": "Daily", "goal": "Run daily"},
        )
        await client.post(
            "/api/work/apps/ops/jobs/daily/automations",
            json={"id": "linked", "name": "Linked", "trigger": {"type": "manual"}},
        )
        await client.post(
            "/api/work/apps/ops/jobs/daily/workflows",
            json={
                "id": "daily-run",
                "name": "Daily run",
                "purpose": "Run the daily operations workflow",
                "type": "manual",
                "automation_id": "linked",
            },
        )
        assert (await client.post("/api/work/apps/ops/jobs/daily/automations/linked/deploy")).status == 202

        rejected = await client.delete("/api/work/apps/ops/jobs/daily/automations/linked")

        assert rejected.status == 409
        assert (await rejected.json())["code"] == "work_conflict"
        assert cancelled == []
        rows = await (await client.get("/api/work/apps/ops/jobs/daily/automations")).json()
        assert rows["automations"][0]["delegation"]["mission_job_id"] == "mission-linked"
    finally:
        await client.close()
