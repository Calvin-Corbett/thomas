from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes.work import register_work_routes
from thomas.server.secrets import SecretStore
from thomas.work import WorkStore


async def _client(root: Path, store: WorkStore, submitter) -> TestClient:
    app = web.Application()
    app[APP_SECRETS] = SecretStore(root / "secrets")
    register_work_routes(
        app,
        require_api_access=lambda request: None,
        store=store,
        mission_submitter=submitter,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def _armed_event(client: TestClient) -> None:
    await client.post("/api/work/apps", json={"id": "mail", "name": "Mail", "goal": "Process mail"})
    await client.post(
        "/api/work/apps/mail/jobs",
        json={"id": "triage", "name": "Triage", "goal": "Triage incoming mail"},
    )
    await client.post(
        "/api/work/apps/mail/jobs/triage/automations",
        json={
            "id": "incoming",
            "name": "Incoming mail",
            "trigger": {"type": "event", "event_name": "mail_received"},
        },
    )
    response = await client.post("/api/work/apps/mail/jobs/triage/automations/incoming/deploy")
    assert response.status == 202


@pytest.mark.asyncio
async def test_ambiguous_mission_response_reuses_delivery_identity(tmp_path: Path) -> None:
    store = WorkStore(tmp_path / "work")
    created: dict[str, str] = {}
    calls: list[str] = []

    async def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        delivery_id = str(payload["payload"]["work_event_delivery_id"])
        calls.append(delivery_id)
        if delivery_id not in created:
            created[delivery_id] = "mission-once"
            raise OSError("response lost after Mission accepted the job")
        return {"job_id": created[delivery_id]}

    client = await _client(tmp_path, store, submitter)
    try:
        await _armed_event(client)
        first = await client.post(
            "/api/work/events/mail_received",
            headers={"Idempotency-Key": "mail-42"},
            json={"subject": "same event"},
        )
        retry = await client.post(
            "/api/work/events/mail_received",
            headers={"Idempotency-Key": "mail-42"},
            json={"subject": "same event"},
        )

        assert first.status == 503
        assert retry.status == 202
        assert len(created) == 1
        assert calls == [calls[0], calls[0]]
        assert (await retry.json())["delegated"][0]["mission_job_id"] == "mission-once"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_receipt_write_failure_reconciles_without_new_mission(tmp_path: Path) -> None:
    store = WorkStore(tmp_path / "work")
    created: dict[str, str] = {}

    async def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        delivery_id = str(payload["payload"]["work_event_delivery_id"])
        created.setdefault(delivery_id, "mission-durable")
        return {"job_id": created[delivery_id]}

    client = await _client(tmp_path, store, submitter)
    try:
        await _armed_event(client)
        persist = store._persist
        failed = False

        def fail_first_delegated_receipt(state: dict[str, Any]) -> None:
            nonlocal failed
            receipts = state["apps"]["mail"]["jobs"]["triage"]["automations"][0]["delegation"].get("event_receipts", [])
            if not failed and any(row.get("state") == "delegated" for row in receipts):
                failed = True
                raise OSError("receipt disk unavailable")
            persist(state)

        store._persist = fail_first_delegated_receipt  # type: ignore[method-assign]
        first = await client.post(
            "/api/work/events/mail_received",
            headers={"Idempotency-Key": "mail-43"},
            json={"subject": "reconcile me"},
        )
        retry = await client.post(
            "/api/work/events/mail_received",
            headers={"Idempotency-Key": "mail-43"},
            json={"subject": "reconcile me"},
        )

        assert first.status == 503
        assert retry.status == 202
        assert len(created) == 1
        assert (await retry.json())["delegated"][0]["mission_job_id"] == "mission-durable"
    finally:
        await client.close()


def test_event_receipts_do_not_evict_old_idempotency_proof(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    store.create_app({"id": "mail", "name": "Mail", "goal": "Process mail"})
    store.create_job("mail", {"id": "triage", "name": "Triage", "goal": "Triage mail"})
    store.create_automation(
        "mail",
        "triage",
        {"id": "incoming", "name": "Incoming", "trigger": {"type": "event", "event_name": "mail_received"}},
    )
    store.arm_event_automation("mail", "triage", "incoming")
    for index in range(101):
        event_id = f"event-{index}"
        assert store.claim_event_delegation("mail", "triage", "incoming", event_id=event_id)["claimed"] is True
        store.record_event_delegation(
            "mail", "triage", "incoming", event_id=event_id, mission_job_id=f"mission-{index}"
        )

    replay = store.claim_event_delegation("mail", "triage", "incoming", event_id="event-0")
    assert replay["claimed"] is False
    assert replay["receipt"]["mission_job_id"] == "mission-0"
