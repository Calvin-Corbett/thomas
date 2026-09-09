from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.work import register_work_routes
from thomas.work import WorkConflictError, WorkCorruptStateError, WorkStore, WorkValidationError


def _job(store: WorkStore) -> tuple[dict[str, Any], dict[str, Any]]:
    app = store.create_app({"id": "dispatch", "name": "Dispatch", "goal": "Keep freight moving"})
    job = store.create_job(
        app["id"],
        {"id": "coordinator", "name": "Coordinator", "goal": "Coordinate daily dispatch"},
    )
    return app, job


def test_automation_trigger_semantics_validate_on_write_and_reload(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    app, job = _job(store)
    with pytest.raises(WorkValidationError, match="automation trigger"):
        store.create_automation(
            app["id"],
            job["id"],
            {"id": "invalid", "name": "Invalid", "trigger": {"type": "garbage"}},
        )
    automation = store.create_automation(
        app["id"],
        job["id"],
        {"id": "event", "name": "Event", "trigger": {"type": "event", "event_name": "mail_received"}},
    )
    with pytest.raises(WorkValidationError, match="trigger.event_name"):
        store.update_automation(app["id"], job["id"], automation["id"], {"trigger": {"type": "event"}})

    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    state["apps"][app["id"]]["jobs"][job["id"]]["automations"][0]["trigger"] = {"type": "garbage"}
    store.state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(WorkCorruptStateError, match="automation definitions"):
        WorkStore(tmp_path)


async def _client(
    root: Path,
    *,
    submitted: list[dict[str, Any]],
    cancelled: list[str],
    submitter_override=None,
) -> TestClient:
    async def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(payload)
        return {"job_id": "mission-workflow-1"}

    async def canceller(job_id: str) -> dict[str, Any]:
        cancelled.append(job_id)
        return {"id": job_id, "status": "cancelled"}

    app = web.Application()
    register_work_routes(
        app,
        require_api_access=lambda request: None,
        store=WorkStore(root),
        mission_submitter=submitter_override or submitter,
        mission_canceller=canceller,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_workflow_routes_run_once_only_through_linked_manual_mission(tmp_path: Path) -> None:
    submitted: list[dict[str, Any]] = []
    cancelled: list[str] = []
    client = await _client(tmp_path, submitted=submitted, cancelled=cancelled)
    try:
        await client.post(
            "/api/work/apps",
            json={"id": "dispatch", "name": "Dispatch", "goal": "Keep freight moving"},
        )
        created_job = await client.post(
            "/api/work/apps/dispatch/jobs",
            json={"id": "coordinator", "name": "Coordinator", "goal": "Coordinate daily dispatch"},
        )
        history_id = (await created_job.json())["job"]["history"]["session_id"]
        created = await client.post(
            "/api/work/apps/dispatch/jobs/coordinator/workflows",
            json={
                "id": "morning",
                "name": "Morning planning",
                "purpose": "Build the owner-ready morning dispatch plan",
                "type": "manual",
                "connector_suggestions": ["gmail"],
            },
        )
        assert created.status == 201
        assert (await created.json())["active_workflow_id"] == "morning"
        await client.post(
            "/api/work/apps/dispatch/jobs/coordinator/workflows",
            json={
                "id": "exceptions",
                "name": "Exception handling",
                "purpose": "Resolve late freight exceptions",
            },
        )
        selected = await client.post("/api/work/apps/dispatch/jobs/coordinator/workflows/exceptions/select")
        assert selected.status == 200
        assert (await selected.json())["active_workflow_id"] == "exceptions"
        await client.post("/api/work/apps/dispatch/jobs/coordinator/workflows/morning/select")
        listed = await client.get("/api/work/apps/dispatch/jobs/coordinator/workflows")
        listed_body = await listed.json()
        assert listed_body["active_workflow_id"] == "morning"
        assert listed_body["workflows"][0]["connector_suggestions"] == ["gmail"]

        await client.post(
            "/api/work/apps/dispatch/jobs/coordinator/automations",
            json={"id": "morning-run", "name": "Morning run", "trigger": {"type": "manual"}},
        )
        await client.patch(
            "/api/work/apps/dispatch/jobs/coordinator/workflows/morning",
            json={"automation_id": "morning-run"},
        )
        await client.patch(
            "/api/work/apps/dispatch/jobs/coordinator/workflows/morning",
            json={"status": "active"},
        )
        run = await client.post("/api/work/apps/dispatch/jobs/coordinator/workflows/morning/run-once")
        body = await run.json()
        assert run.status == 202
        assert body["mission"] == {"job_id": "mission-workflow-1", "delegated": True}
        assert submitted[0]["goal"] == "Build the owner-ready morning dispatch plan"
        assert submitted[0]["payload"]["work_workflow_id"] == "morning"
        assert submitted[0]["session_id"] == history_id
        assert submitted[0]["payload"]["connector_bindings"] == []

        paused = await client.post("/api/work/apps/dispatch/jobs/coordinator/pause")
        assert paused.status == 200
        assert cancelled == ["mission-workflow-1"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_concurrent_run_once_submits_exactly_one_mission(tmp_path: Path) -> None:
    submitted: list[dict[str, Any]] = []
    submission_started = asyncio.Event()
    release_submission = asyncio.Event()

    async def delayed_submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(payload)
        submission_started.set()
        await release_submission.wait()
        return {"job_id": "mission-only-once"}

    client = await _client(
        tmp_path,
        submitted=submitted,
        cancelled=[],
        submitter_override=delayed_submitter,
    )
    try:
        await client.post("/api/work/apps", json={"id": "dispatch", "name": "Dispatch", "goal": "Move freight"})
        await client.post(
            "/api/work/apps/dispatch/jobs",
            json={"id": "coordinator", "name": "Coordinator", "goal": "Coordinate dispatch"},
        )
        await client.post(
            "/api/work/apps/dispatch/jobs/coordinator/workflows",
            json={"id": "morning", "name": "Morning", "purpose": "Build the morning plan"},
        )
        await client.post(
            "/api/work/apps/dispatch/jobs/coordinator/automations",
            json={"id": "morning-run", "name": "Morning run", "trigger": {"type": "manual"}},
        )
        await client.patch(
            "/api/work/apps/dispatch/jobs/coordinator/workflows/morning",
            json={"automation_id": "morning-run"},
        )
        await client.patch(
            "/api/work/apps/dispatch/jobs/coordinator/workflows/morning",
            json={"status": "active"},
        )
        url = "/api/work/apps/dispatch/jobs/coordinator/workflows/morning/run-once"
        first = asyncio.create_task(client.post(url))
        await asyncio.wait_for(submission_started.wait(), timeout=2)
        duplicate = await client.post(url)
        assert duplicate.status == 409
        assert "already has a Mission run" in (await duplicate.json())["error"]
        assert len(submitted) == 1
        release_submission.set()
        assert (await first).status == 202
    finally:
        release_submission.set()
        await client.close()


@pytest.mark.asyncio
async def test_workflow_run_once_rejects_unselected_and_scheduled_automations(tmp_path: Path) -> None:
    submitted: list[dict[str, Any]] = []
    client = await _client(tmp_path, submitted=submitted, cancelled=[])
    try:
        await client.post(
            "/api/work/apps",
            json={"id": "dispatch", "name": "Dispatch", "goal": "Keep freight moving"},
        )
        await client.post(
            "/api/work/apps/dispatch/jobs",
            json={"id": "coordinator", "name": "Coordinator", "goal": "Coordinate dispatch"},
        )
        await client.post(
            "/api/work/apps/dispatch/jobs/coordinator/workflows",
            json={
                "id": "scheduled",
                "name": "Scheduled",
                "purpose": "Build a scheduled report",
                "type": "scheduled",
            },
        )
        await client.post(
            "/api/work/apps/dispatch/jobs/coordinator/automations",
            json={
                "id": "daily-report",
                "name": "Daily report",
                "trigger": {"type": "daily", "at": "08:00"},
            },
        )
        await client.patch(
            "/api/work/apps/dispatch/jobs/coordinator/workflows/scheduled",
            json={"automation_id": "daily-report"},
        )

        inactive = await client.post("/api/work/apps/dispatch/jobs/coordinator/workflows/scheduled/run-once")
        assert inactive.status == 409
        await client.patch(
            "/api/work/apps/dispatch/jobs/coordinator/workflows/scheduled",
            json={"status": "active"},
        )
        scheduled = await client.post("/api/work/apps/dispatch/jobs/coordinator/workflows/scheduled/run-once")
        assert scheduled.status == 409
        assert "linked manual automation" in (await scheduled.json())["error"]
        deployed = await client.post("/api/work/apps/dispatch/jobs/coordinator/automations/daily-report/deploy")
        assert deployed.status == 202
        assert submitted[0]["goal"] == "Build a scheduled report"
        assert submitted[0]["payload"]["work_workflow_id"] == "scheduled"
    finally:
        await client.close()
