"""Schedules have a page, not only a CLI (frontier parity: Claude Code /schedule, ChatGPT tasks, Chrome scheduled tasks)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.scheduler import TaskScheduler
from thomas.server.routes.schedule_routes import setup_schedule_routes


def _scheduler(tmp_path: Path, calls: list) -> TaskScheduler:
    return TaskScheduler(
        execute_fn=lambda goal, channel: calls.append((goal, channel)),
        schedule_path=tmp_path / "schedules.json",
        auto_start=False,
    )


def test_list_add_pause_resume_run_and_remove_over_http(tmp_path: Path) -> None:
    calls: list = []
    sched = _scheduler(tmp_path, calls)
    app = web.Application()
    setup_schedule_routes(app, scheduler=sched, require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            empty = await (await client.get("/api/schedules")).json()
            assert empty["tasks"] == []
            created = await client.post(
                "/api/schedules", json={"cron": "0 9 * * 1-5", "task": "Summarise my inbox", "channel": "default"}
            )
            assert created.status == 200, await created.text()
            task_id = (await created.json())["task"]["id"]
            listed = await (await client.get("/api/schedules")).json()
            assert [t["id"] for t in listed["tasks"]] == [task_id]
            assert listed["tasks"][0]["cron"] == "0 9 * * 1-5"
            assert (await client.post(f"/api/schedules/{task_id}/pause")).status == 200
            assert (await (await client.get("/api/schedules")).json())["tasks"][0]["status"] == "paused"
            assert (await client.post(f"/api/schedules/{task_id}/resume")).status == 200
            assert (await client.post(f"/api/schedules/{task_id}/run")).status == 200
            assert (await client.delete(f"/api/schedules/{task_id}")).status == 200
            assert (await (await client.get("/api/schedules")).json())["tasks"] == []
            assert (await client.delete("/api/schedules/nope")).status == 404
            bad = await client.post("/api/schedules", json={"cron": "not a cron", "task": "x"})
            assert bad.status == 400

    asyncio.run(scenario())
