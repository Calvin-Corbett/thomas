"""Starter and interrupted-start recovery reuse the shared listing refresh."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from tests.test_project_queue_cached_capacity import _client, _room, post, w  # noqa: F401
from thomas.server import self_improvement_planner, self_project_queue, self_project_queue_tick, thomas_project
from thomas.server.routes import self_project_routes


def test_starter_returns_while_a_dirty_snapshot_is_being_refreshed(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        entered, release = threading.Event(), threading.Event()
        calls = 0

        def reader(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                entered.set()
                assert release.wait(10), "test did not release the full scanner"
            return {"ok": True, "projects": [], "unreadable": []}

        try:
            _room(monkeypatch)
            monkeypatch.setattr(self_project_routes, "read_projects", reader)
            monkeypatch.setattr(self_improvement_planner, "scan", lambda *_args, **_kwargs: [])
            client.app["queue_test_port"] = client.port
            await post(client)
            await self_project_queue_tick.project_listing(client.app)
            client.app["self_project_listing_slot"]["dirty"] = True
            await asyncio.wait_for(self_project_queue_tick.tick(client.app, w.catalog), 1)
            assert await asyncio.to_thread(entered.wait, 2)
            assert not release.is_set()
            assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")
        finally:
            release.set()
            slot = client.app["self_project_listing_slot"]
            if slot.get("task"):
                await asyncio.wait_for(slot["task"], 5)
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "report",
    [
        {"ok": False, "projects": [], "unreadable": [], "error": "catalog unavailable"},
        {"ok": True, "projects": [], "unreadable": [], "incomplete": True},
    ],
)
def test_failed_listing_report_cannot_authorize_a_start(w, monkeypatch, report):
    from thomas.server import self_project_queue

    async def scenario():
        client = await _client(w)
        try:
            monkeypatch.setattr(
                self_project_routes,
                "read_projects",
                lambda *_: report,
            )
            await post(client)
            status = (await (await client.get("/api/self/projects/queue")).json())["capacity"]
            assert status["running"] is None
            assert "read" in status["blocked_by"]
            assert not await asyncio.to_thread(
                self_project_queue_tick._select, w.catalog, client.app, client.port, time.time()
            )
            assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")
        finally:
            await client.close()

    asyncio.run(scenario())


def test_recovery_waits_for_shared_refresh_without_rescanning_projects(w, monkeypatch):
    row = self_project_queue.enqueue(w.catalog, "Interrupted start", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": 1, "pid": 1}))
    monkeypatch.setattr(
        self_project_routes, "read_projects", lambda *_a, **_k: pytest.fail("recovery must reuse the shared refresh")
    )
    _, refresh_needed = self_project_queue_tick._reconcile(w.catalog, 0, [], set())
    data = self_project_queue.read(w.catalog)
    assert refresh_needed and data["queued"][0]["starting"]
    assert not data["started"] and not data["given_up"]
    projects = [{"queue_id": row["id"], "conversation_id": "recovered", "execution_id": "run"}]
    self_project_queue_tick._reconcile(w.catalog, 0, projects, set())
    data = self_project_queue.read(w.catalog)
    assert data["started"][0]["conversation_id"] == "recovered"
    assert not data["queued"] and not data["given_up"]


def test_recovery_does_not_discard_reservation_it_did_not_scan(w, monkeypatch):
    first = self_project_queue.enqueue(w.catalog, "First interrupted start", {}, "", 1)
    second = self_project_queue.enqueue(w.catalog, "Second interrupted start", {}, "", 1)

    def reserve(data):
        for row in data["queued"]:
            row["starting"] = {"at": 1, "pid": 1}

    self_project_queue.change(w.catalog, reserve)
    self_project_queue_tick._in_flight.add(second["id"])

    def conversations(_catalog, _wanted):
        self_project_queue_tick._in_flight.discard(second["id"])
        return {first["id"]: {"conversation_id": "first", "execution_id": "run"}}

    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", conversations)
    try:
        self_project_queue_tick._reconcile(w.catalog, 0, [], set())
        data = self_project_queue.read(w.catalog)
        assert data["started"][0]["id"] == first["id"]
        assert [row["id"] for row in data["queued"]] == [second["id"]]
        assert not data["given_up"]
    finally:
        self_project_queue_tick._in_flight.discard(second["id"])


def test_recovery_keeps_a_replaced_reservation(w, monkeypatch):
    row = self_project_queue.enqueue(w.catalog, "Interrupted start", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": 1, "pid": 1}))

    def conversations(_catalog, _wanted):
        self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": 2, "pid": 2}))
        return {row["id"]: {"id": "old", "thomas_project": {"execution_id": "old-run"}}}

    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", conversations)
    self_project_queue_tick._reconcile(w.catalog, 0, [], set())
    data = self_project_queue.read(w.catalog)
    assert not data["started"] and not data["given_up"]
    assert data["queued"][0]["starting"] == {"at": 2, "pid": 2}


def test_recovery_waits_when_discovery_is_incomplete(w, monkeypatch):
    row = self_project_queue.enqueue(w.catalog, "Interrupted start", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": 1, "pid": 1}))
    monkeypatch.setattr(
        self_project_routes,
        "read_projects",
        lambda *_args, **_kw: {"ok": True, "projects": [], "unreadable": ["green"]},
    )
    self_project_queue_tick._reconcile(w.catalog, 0, [], set())
    data = self_project_queue.read(w.catalog)
    assert not data["started"] and not data["given_up"]
    assert data["queued"][0]["id"] == row["id"] and data["queued"][0]["starting"]


def test_interrupted_start_waits_for_shared_refresh_without_blocking_capacity(w, monkeypatch):
    async def scenario():
        client = await _client(w)
        entered, release = threading.Event(), threading.Event()
        calls = 0

        def reader(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            entered.set()
            release.wait(5)
            return {"ok": True, "projects": [], "unreadable": []}

        try:
            await client.get("/api/self/projects")
            ask = await post(client)
            self_project_queue.change(
                w.catalog,
                lambda data: data["queued"][0].update(starting={"pid": 1, "at": time.time()}),
            )
            monkeypatch.setattr(self_project_routes, "read_projects", reader)
            client.app["self_project_listing_slot"]["updated"] = 0
            await self_project_queue_tick.project_listing(client.app)
            assert (
                await asyncio.wait_for(
                    asyncio.to_thread(self_project_queue_tick._select, w.catalog, client.app, client.port, time.time()),
                    timeout=5,
                )
                is None
            )
            assert not release.is_set(), "selection must return before the shared inventory finishes"
            await asyncio.wait_for(client.get("/api/self/queue"), timeout=2)
            assert await asyncio.to_thread(entered.wait, 1)
            assert calls == 1
            slot = client.app["self_project_listing_slot"]
            assert not slot.get("dirty")
            release.set()
            await asyncio.wait_for(slot["task"], 2)
            assert calls == 1
            assert slot["captured_at"] >= self_project_queue.read(w.catalog)["queued"][0]["starting"]["at"]
            row = self_project_queue.read(w.catalog)["queued"][0]
            assert row["id"] == ask["id"] and row["starting"]
            assert not self_project_queue.read(w.catalog)["given_up"]
        finally:
            release.set()
            await client.close()

    asyncio.run(scenario())


def test_cold_starter_refreshes_once_then_starts_without_opening_project_list(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    _room(monkeypatch)
    monkeypatch.setattr(self_improvement_planner, "scan", lambda *_args, **_kwargs: [])

    async def scenario():
        client = await _client(w)
        entered, release, started = threading.Event(), threading.Event(), asyncio.Event()
        calls = []

        def scan(*_):
            calls.append(1)
            entered.set()
            assert release.wait(10)
            return {"ok": True, "projects": [], "unreadable": []}

        async def start(_app, **_kwargs):
            started.set()
            return {"conversation_id": "started", "execution_id": "run"}

        monkeypatch.setattr(self_project_routes, "read_projects", scan)
        monkeypatch.setattr(thomas_project, "start_thomas_project", start)
        try:
            client.app["queue_test_port"] = client.port
            await post(client)
            await asyncio.wait_for(self_project_queue_tick.tick(client.app, w.catalog), 2)
            assert entered.is_set() and not started.is_set()
            for _ in range(3):
                await asyncio.wait_for(self_project_queue_tick.tick(client.app, w.catalog), 1)
            assert calls == [1]
            release.set()
            await asyncio.wait_for(client.app["self_project_listing_slot"]["task"], 2)
            await self_project_queue_tick.tick(client.app, w.catalog)
            await asyncio.wait_for(started.wait(), 2)
            for _ in range(100):
                if not self_project_queue_tick._in_flight:
                    break
                await asyncio.sleep(0.01)
            assert calls == [1]
            assert self_project_queue.read(w.catalog)["started"]
        finally:
            release.set()
            task = client.app["self_project_listing_slot"].get("task")
            if task:
                await asyncio.wait_for(task, 5)
            await client.close()

    asyncio.run(scenario())
