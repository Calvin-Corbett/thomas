"""Planner projects use valid settings and expose start refusals through the queue."""

from __future__ import annotations

import asyncio
import time

from tests.test_a_self_project_queue import _room, isolated  # noqa: F401
from tests.test_a_thomas_project_starts_without_chat import _client, w  # noqa: F401
from thomas.server import self_improvement_planner, self_project_queue, self_project_queue_tick, thomas_project
from thomas.server.routes.self_project_routes import _checked


def test_planner_books_guarded_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(self_improvement_planner, "enabled", lambda data: True)
    monkeypatch.setattr(
        self_improvement_planner,
        "propose",
        lambda *args, **kwargs: [{"key": "build", "request": "Fix the build", "source": "pytest", "source_id": "t"}],
    )
    booked = self_improvement_planner.scan(tmp_path, 8765, now=100000)
    assert len(booked) == 1
    queued = self_project_queue.read(tmp_path)["queued"][0]
    assert queued["settings"]["guardrails"] == "guarded"
    assert not hasattr(_checked({"request": queued["request"], "settings": queued["settings"]}), "status")


def test_previously_booked_planner_project_starts_and_keeps_valid_settings(w, monkeypatch):
    async def scenario():
        client = await _client(w)
        try:
            _room(monkeypatch)
            row = self_project_queue.new_entry(
                "Fix the build",
                {"autonomy_level": 5, "file_access": "project", "guardrails": "standard"},
                "",
                client.port,
            )
            row.update({"origin": "pytest", "source_id": "t", "queued_at": 100000})
            self_project_queue.change(w.catalog, lambda data: data["queued"].append(row))
            started = []

            async def start(app, **kwargs):
                started.append(kwargs)
                return {"conversation_id": "c", "execution_id": "e"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            monkeypatch.setattr(self_improvement_planner, "enabled", lambda data: True)
            monkeypatch.setattr(self_improvement_planner, "scan", lambda *args, **kwargs: [])
            await self_project_queue_tick.project_listing(client.app)
            selected = self_project_queue_tick._select(w.catalog, client.app, client.port, time.time())
            assert selected is not None
            await self_project_queue_tick._start(client.app, w.catalog, selected, client.port)
            assert len(started) == 1
            assert started[0]["settings"]["guardrails"] == "guarded"
            assert self_project_queue.read(w.catalog)["started"][0]["settings"]["guardrails"] == "guarded"
            assert not self_project_queue.read(w.catalog)["given_up"]
            assert row["id"] == started[0]["meta"]["queue_id"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_unstartable_project_reason_is_visible_in_queue_api(w, monkeypatch):
    async def scenario():
        client = await _client(w)
        try:
            _room(monkeypatch)
            row = self_project_queue.enqueue(
                w.catalog,
                "Fix the build",
                {"autonomy_level": 5, "file_access": "project", "guardrails": "guarded"},
                "",
                client.port,
            )

            def break_settings(data):
                data["queued"][0]["settings"]["guardrails"] = "not-a-preset"

            self_project_queue.change(w.catalog, break_settings)
            await self_project_queue_tick.project_listing(client.app)
            self_project_queue_tick._select(w.catalog, client.app, client.port, time.time())
            response = await client.get("/api/self/projects/queue")
            assert response.status == 200
            listed = await response.json()
            assert listed["queued"] == []
            assert listed["given_up"][0]["id"] == row["id"]
            assert "invalid guardrails" in listed["given_up"][0]["reason"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_retry_failures_keep_their_reason_after_retries_are_exhausted(w):
    async def scenario():
        client = await _client(w)
        try:
            row = self_project_queue.enqueue(
                w.catalog,
                "Fix the build",
                {"autonomy_level": 5, "file_access": "project", "guardrails": "guarded"},
                "",
                client.port,
            )
            for _ in range(self_project_queue_tick.MAX_START_TRIES):
                self_project_queue_tick._failed(w.catalog, row["id"], "workspace cannot be prepared")
            response = await client.get("/api/self/projects/queue")
            assert response.status == 200
            listed = await response.json()
            assert listed["queued"][0]["id"] == row["id"]
            assert listed["queued"][0]["last_reason"] == "workspace cannot be prepared"
            assert listed["queued"][0]["given_up"] is True
            assert listed["queued"][0]["tries"] == self_project_queue_tick.MAX_START_TRIES
        finally:
            await client.close()

    asyncio.run(scenario())
