"""The gate through the real HTTP route, not just the decision function.

A gate that is correct in isolation and unreachable from the route is the shape
this repo keeps producing. These drive `POST /api/work/apps/<id>/jobs`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.work import register_work_routes
from thomas.work import WorkStore
from thomas.work.lanes.onboarding_gate import LANE_GATE_FLAG


async def _client(store: WorkStore) -> TestClient:
    app = web.Application()
    register_work_routes(app, require_api_access=lambda request: None, store=store, mission_canceller=None)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def _store(tmp_path: Path, *, in_flight: bool) -> WorkStore:
    store = WorkStore(tmp_path)
    store.create_app({"id": "ops", "name": "Ops", "goal": "Operate"})
    if in_flight:
        store.update_onboarding("ops", {"state": "collecting", "phase": "goal_discovery"})
    return store


@pytest.mark.asyncio
async def test_the_route_refuses_a_job_while_onboarding_collects(tmp_path: Path):
    client = await _client(_store(tmp_path, in_flight=True))
    try:
        response = await client.post("/api/work/apps/ops/jobs", json={"name": "Skip the questions"})
        assert response.status == 409
        body = await response.json()
        assert body["ok"] is False
        assert "onboarding is not finished" in body["error"]
        assert LANE_GATE_FLAG in body["error"], "a wrong gate must never be a dead end"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_the_route_still_creates_a_job_for_a_settled_app(tmp_path: Path):
    client = await _client(_store(tmp_path, in_flight=False))
    try:
        response = await client.post("/api/work/apps/ops/jobs", json={"name": "Daily reconcile"})
        assert response.status == 201
        assert (await response.json())["job"]["name"] == "Daily reconcile"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_an_explicit_waiver_creates_the_job_and_marks_it(tmp_path: Path):
    store = _store(tmp_path, in_flight=True)
    client = await _client(store)
    try:
        response = await client.post(
            "/api/work/apps/ops/jobs",
            json={"name": "Create anyway", "waive_lane": True},
        )
        assert response.status == 201
        job = (await response.json())["job"]
        assert job["metadata"]["lane_waived"] is True
        assert "goal_discovery" in job["metadata"]["lane_reason"], "the skip says what was skipped"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_created_job_without_a_waiver_carries_no_lane_marks(tmp_path: Path):
    client = await _client(_store(tmp_path, in_flight=False))
    try:
        response = await client.post("/api/work/apps/ops/jobs", json={"name": "Clean"})
        job = (await response.json())["job"]
        assert "lane_waived" not in (job.get("metadata") or {})
    finally:
        await client.close()
