from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes.work import APP_WORK_STORE, register_work_routes
from thomas.server.secrets import SecretStore
from thomas.work import WorkStore


async def _client(
    root: Path,
    *,
    submitter=None,
    status_provider=None,
    canceller=None,
) -> TestClient:
    app = web.Application()
    app[APP_SECRETS] = SecretStore(root / "secrets")
    register_work_routes(
        app,
        require_api_access=lambda request: None,
        store=WorkStore(root),
        mission_submitter=submitter,
        mission_status_provider=status_provider,
        mission_canceller=canceller,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_pausing_event_job_cancels_every_active_mission(tmp_path: Path) -> None:
    submitted: list[str] = []
    cancelled: list[str] = []

    async def submitter(_payload: dict[str, Any]) -> dict[str, Any]:
        mission_id = f"mission-{len(submitted) + 1}"
        submitted.append(mission_id)
        return {"job_id": mission_id}

    async def canceller(job_id: str) -> dict[str, Any]:
        cancelled.append(job_id)
        return {"id": job_id, "status": "cancelled"}

    client = await _client(tmp_path, submitter=submitter, canceller=canceller)
    try:
        await client.post("/api/work/apps", json={"id": "mail", "name": "Mail", "goal": "Triage"})
        await client.post(
            "/api/work/apps/mail/jobs",
            json={"id": "triage", "name": "Triage", "goal": "Triage mail"},
        )
        await client.post(
            "/api/work/apps/mail/jobs/triage/automations",
            json={
                "id": "event",
                "name": "Event",
                "trigger": {"type": "event", "event_name": "message_received"},
            },
        )
        assert (await client.post("/api/work/apps/mail/jobs/triage/automations/event/deploy")).status == 202
        for index in range(2):
            response = await client.post(
                "/api/work/events/message_received",
                json={"event_id": f"message-{index}", "message": index},
            )
            assert response.status == 202

        paused = await client.post("/api/work/apps/mail/jobs/triage/pause")

        assert paused.status == 200
        assert submitted == ["mission-1", "mission-2"]
        assert cancelled == ["mission-1", "mission-2"]
        automation = await (await client.get("/api/work/apps/mail/jobs/triage/automations")).json()
        assert automation["automations"][0]["delegation"]["active_mission_job_ids"] == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_partial_event_cancellation_is_checkpointed_for_safe_retry(tmp_path: Path) -> None:
    submitted: list[str] = []
    attempts: list[str] = []

    async def submitter(_payload: dict[str, Any]) -> dict[str, Any]:
        mission_id = f"mission-{len(submitted) + 1}"
        submitted.append(mission_id)
        return {"job_id": mission_id}

    async def canceller(job_id: str) -> dict[str, Any]:
        attempts.append(job_id)
        if job_id == "mission-2" and attempts.count(job_id) == 1:
            raise RuntimeError("temporary Mission failure")
        return {"id": job_id, "status": "cancelled"}

    client = await _client(tmp_path, submitter=submitter, canceller=canceller)
    try:
        await client.post("/api/work/apps", json={"id": "mail", "name": "Mail", "goal": "Triage"})
        await client.post(
            "/api/work/apps/mail/jobs",
            json={"id": "triage", "name": "Triage", "goal": "Triage mail"},
        )
        await client.post(
            "/api/work/apps/mail/jobs/triage/automations",
            json={
                "id": "event",
                "name": "Event",
                "trigger": {"type": "event", "event_name": "message_received"},
            },
        )
        await client.post("/api/work/apps/mail/jobs/triage/automations/event/deploy")
        await client.post("/api/work/events/message_received", json={"event_id": "message-1", "message": 1})
        await client.post("/api/work/events/message_received", json={"event_id": "message-2", "message": 2})

        first_pause = await client.post("/api/work/apps/mail/jobs/triage/pause")
        after_failure = client.server.app[APP_WORK_STORE].list_automations("mail", "triage")[0]
        second_pause = await client.post("/api/work/apps/mail/jobs/triage/pause")

        assert first_pause.status == 503
        assert after_failure["delegation"]["active_mission_job_ids"] == ["mission-2"]
        assert after_failure["delegation"]["last_run"]["mission_job_id"] == "mission-1"
        assert second_pause.status == 200
        assert attempts == ["mission-1", "mission-2", "mission-2"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_event_fanout_retry_does_not_duplicate_completed_flow(tmp_path: Path) -> None:
    attempts: list[str] = []

    async def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        automation_id = str(payload["payload"]["work_automation_id"])
        attempts.append(automation_id)
        if automation_id == "event-b" and attempts.count(automation_id) == 1:
            raise RuntimeError("temporary Mission failure")
        return {"job_id": f"mission-{automation_id}-{attempts.count(automation_id)}"}

    client = await _client(tmp_path, submitter=submitter)
    try:
        await client.post("/api/work/apps", json={"id": "ops", "name": "Operations", "goal": "Route events"})
        for suffix in ("a", "b"):
            await client.post(
                "/api/work/apps/ops/jobs",
                json={"id": f"job-{suffix}", "name": f"Job {suffix}", "goal": f"Process flow {suffix}"},
            )
            await client.post(
                f"/api/work/apps/ops/jobs/job-{suffix}/automations",
                json={
                    "id": f"event-{suffix}",
                    "name": f"Event {suffix}",
                    "trigger": {"type": "event", "event_name": "message_received"},
                },
            )
            await client.post(f"/api/work/apps/ops/jobs/job-{suffix}/automations/event-{suffix}/deploy")

        first = await client.post(
            "/api/work/events/message_received",
            headers={"Idempotency-Key": "delivery-42"},
            json={"message": "same delivery"},
        )
        retry = await client.post(
            "/api/work/events/message_received",
            headers={"Idempotency-Key": "delivery-42"},
            json={"message": "same delivery"},
        )
        retry_body = await retry.json()

        assert first.status == 503
        assert retry.status == 202
        assert attempts == ["event-a", "event-b", "event-b"]
        assert retry_body["delegated"][0]["replayed"] is True
        store = client.server.app[APP_WORK_STORE]
        assert store.list_automations("ops", "job-a")[0]["delegation"]["active_mission_job_ids"] == [
            "mission-event-a-1"
        ]
        assert store.list_automations("ops", "job-b")[0]["delegation"]["active_mission_job_ids"] == [
            "mission-event-b-2"
        ]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_event_delivery_requires_stable_identity(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        response = await client.post("/api/work/events/message_received", json={"message": "missing identity"})
        assert response.status == 400
        assert "Idempotency-Key" in (await response.json())["error"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_event_deploy_validates_job_and_enabled_state_and_edit_disarms(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        await client.post("/api/work/apps", json={"id": "mail", "name": "Mail", "goal": "Triage"})
        await client.post(
            "/api/work/apps/mail/jobs",
            json={"id": "triage", "name": "Triage", "goal": "Triage mail"},
        )
        await client.post(
            "/api/work/apps/mail/jobs/triage/automations",
            json={
                "id": "event",
                "name": "Event",
                "enabled": False,
                "trigger": {"type": "event", "event_name": "message_received"},
            },
        )
        route = "/api/work/apps/mail/jobs/triage/automations/event"
        assert (await client.post(f"{route}/deploy")).status == 409
        assert (await client.patch(route, json={"enabled": True})).status == 200
        assert (await client.post("/api/work/apps/mail/jobs/triage/pause")).status == 200
        assert (await client.post(f"{route}/deploy")).status == 409
        assert (await client.post("/api/work/apps/mail/jobs/triage/resume")).status == 200
        assert (await client.post(f"{route}/deploy")).status == 202

        edited = await client.patch(route, json={"trigger": {"type": "manual"}})

        assert edited.status == 200
        assert (await edited.json())["automation"]["delegation"]["state"] == "not_deployed"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mismatched_mission_status_receipt_fails_closed_and_run_remains_cancellable(tmp_path: Path) -> None:
    cancelled: list[str] = []

    async def submitter(_payload: dict[str, Any]) -> dict[str, Any]:
        return {"job_id": "mission-real"}

    async def status_provider(_job_id: str) -> dict[str, Any]:
        return {"id": "mission-other", "status": "succeeded"}

    async def canceller(job_id: str) -> dict[str, Any]:
        cancelled.append(job_id)
        return {"id": job_id, "status": "cancelled"}

    client = await _client(
        tmp_path,
        submitter=submitter,
        status_provider=status_provider,
        canceller=canceller,
    )
    try:
        await client.post("/api/work/apps", json={"id": "ops", "name": "Ops", "goal": "Operate"})
        await client.post(
            "/api/work/apps/ops/jobs",
            json={"id": "daily", "name": "Daily", "goal": "Run daily"},
        )
        await client.post(
            "/api/work/apps/ops/jobs/daily/automations",
            json={"id": "run", "name": "Run", "trigger": {"type": "manual"}},
        )
        assert (await client.post("/api/work/apps/ops/jobs/daily/automations/run/deploy")).status == 202

        reconciled = await client.get("/api/work/apps/ops/jobs/daily/automations")
        paused = await client.post("/api/work/apps/ops/jobs/daily/pause")

        assert reconciled.status == 503
        assert paused.status == 200
        assert cancelled == ["mission-real"]
    finally:
        await client.close()
