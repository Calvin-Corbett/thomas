"""Capacity and dispatch stay bounded while many projects' full listing is slow."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core import machine_capacity, persistence
from thomas.server import (
    autopilot_hold_tick,
    capacity_ledger,
    self_improvement_planner,
    self_project_queue,
    self_project_queue_tick,
    thomas_project,
)
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import self_project_queue_routes, self_project_routes

URL = self_project_queue_routes.PATH


@pytest.fixture
def w(tmp_path, monkeypatch):
    # These tests replace the full reader and project launcher. A source checkout,
    # git commits, preferences database, and whole-server startup are not needed.
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    monkeypatch.setattr(persistence, "_DEFAULT_STATE_FILE", tmp_path / "data" / "thomas_state.json")
    monkeypatch.setattr(persistence, "_DEFAULT_REPORT_DIR", tmp_path / "data" / "reports")
    monkeypatch.setattr(persistence, "_engine", None)
    monkeypatch.setenv("THOMAS_CAPACITY_LEDGER_ROOT", str(catalog / ".thomas" / "evolve" / "agent"))
    monkeypatch.setattr(autopilot_hold_tick, "port_of", lambda app: int(app.get("queue_test_port", 0)))
    monkeypatch.setattr(self_improvement_planner, "scan", lambda *_args, **_kwargs: [])

    async def hook(*_args, **_kwargs):
        pytest.fail("the real Build launcher must not run in cache regressions")

    return SimpleNamespace(catalog=catalog, hook=hook)


def _room(monkeypatch, *, rows=None):
    monkeypatch.setattr(machine_capacity, "_memory", lambda: (16 * 1024**3, 8 * 1024**3))
    monkeypatch.setattr(
        self_project_routes, "read_projects", lambda *a, **kw: {"projects": rows or [], "unreadable": []}
    )
    monkeypatch.setattr(machine_capacity, "admission_refusal", lambda _active: None)
    monkeypatch.setattr(capacity_ledger, "refusal", lambda *a, **kw: None)
    monkeypatch.setattr(capacity_ledger, "rows", lambda: [])
    monkeypatch.setattr(capacity_ledger, "measure", lambda _root: capacity_ledger.Room(100 * 1024**3, None, None))


async def post(client, ask="Cache regression"):
    # Seed a real durable queue entry; route validation has its own integration
    # coverage and does not affect snapshot sharing or dispatch selection.
    return await asyncio.to_thread(self_project_queue.enqueue, thomas_project._catalog_root(), ask, {}, "", client.port)


async def _client(w) -> TestClient:
    """Exercise the real routes without booting unrelated server services.

    Full-server startup/shutdown belongs to the existing integration tests. In
    these timing regressions it can consume the verifier's entire time budget,
    independently of the cache and queue behavior under test.
    """
    app = web.Application()
    app[APP_PRAXIS_START_CODE_RUN] = w.hook

    def require_loopback(request: web.Request) -> None:
        if request.remote not in {"127.0.0.1", "::1"}:
            raise web.HTTPForbidden()

    self_project_routes.register_self_project_routes(app, require_loopback=require_loopback)
    self_project_queue_routes.register_self_project_queue_routes(app, require_loopback=require_loopback)
    client = TestClient(TestServer(app, host="127.0.0.1"))
    await client.start_server()
    return client


def test_capacity_and_starter_listing_reuse_a_fresh_route_snapshot(w, monkeypatch):
    snapshot = {"ok": True, "projects": [{"conversation_id": "running", "state": "running"}], "unreadable": []}
    app = {"self_project_listing_slot": {"snapshot": snapshot, "updated": time.monotonic()}}

    def unexpected_scan(*_args, **_kwargs):
        pytest.fail("a fresh project-route snapshot must not be rebuilt for capacity or dispatch")

    monkeypatch.setattr(self_project_routes, "read_projects", unexpected_scan)
    assert asyncio.run(self_project_queue_tick.project_listing(app)) is snapshot
    assert "task" not in app["self_project_listing_slot"], "a fresh snapshot must not launch another inventory scan"


@pytest.mark.parametrize("project_count", [20, 200])
def test_warm_capacity_and_dispatch_do_not_wait_for_many_project_refresh(w, monkeypatch, project_count):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        entered, release = threading.Event(), threading.Event()
        calls = 0
        running = {f"running-{n}" for n in range(project_count)}
        projects = [{"conversation_id": cid, "state": "running"} for cid in sorted(running)]
        started = asyncio.Event()
        finish_start = asyncio.Event()

        def reader(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                entered.set()
                assert release.wait(60), "test did not release the full scanner"
            return {"ok": True, "projects": projects, "unreadable": []}

        async def start(_app, **_kwargs):
            started.set()
            await finish_start.wait()
            return {"conversation_id": "new-project", "execution_id": "new-execution"}

        try:
            _room(monkeypatch)
            monkeypatch.setenv("THOMAS_SELF_PROJECT_PARALLEL", str(project_count + 2))
            monkeypatch.setattr(self_project_routes, "running_projects", lambda _app: running)
            monkeypatch.setattr(self_project_routes, "_running", lambda _app: running)
            monkeypatch.setattr(self_project_routes, "read_projects", reader)
            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            monkeypatch.setattr(self_improvement_planner, "scan", lambda *_args, **_kwargs: [])
            client.app["queue_test_port"] = client.port
            queued = await post(client)
            listing = await (await client.get("/api/self/projects")).json()
            assert len(listing["projects"]) == project_count and calls == 1
            slot = client.app["self_project_listing_slot"]
            slot["updated"] = 0
            refreshing = await (await client.get("/api/self/projects")).json()
            assert refreshing["refreshing"]
            assert await asyncio.to_thread(entered.wait, 2)

            before = time.monotonic()
            response = await asyncio.wait_for(client.get(URL), 5)
            capacity = (await response.json())["capacity"]
            assert capacity["running"] == project_count
            assert capacity["blocked_by"] is None
            await asyncio.wait_for(self_project_queue_tick.tick(client.app, w.catalog), 5)
            await asyncio.wait_for(started.wait(), 5)
            elapsed = time.monotonic() - before

            def unexpected_scan(*_args, **_kwargs):
                raise AssertionError("a pending in-memory start must not rescan the catalog or greens")

            monkeypatch.setattr(self_project_routes, "_conversations", unexpected_scan)
            monkeypatch.setattr(thomas_project, "_read_live", unexpected_scan)
            # Capacity and subsequent ticks must also stay fast while the start is pending.
            for _ in range(2):
                pending = (await (await asyncio.wait_for(client.get(URL), 5)).json())["capacity"]
                assert pending["starting"] == 1
                assert pending["blocked_by"] is None
                await asyncio.wait_for(self_project_queue_tick.tick(client.app, w.catalog), 5)
            assert calls == 2  # one shared refresh, never a capacity/starter scan
            assert not release.is_set()  # dispatch happened before the full listing finished
            assert self_project_queue.read(w.catalog)["queued"][0]["id"] == queued["id"]
            print(f"{project_count} running projects: capacity + dispatch {elapsed:.3f}s; scanner still blocked")
        finally:
            finish_start.set()
            for task in list(self_project_queue_tick._start_tasks):
                await asyncio.wait_for(task, 5)
            release.set()
            slot = client.app["self_project_listing_slot"]
            if slot.get("task"):
                await asyncio.wait_for(slot["task"], 5)
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "interleaving", ["dirty", "invalidated", "refreshed", "live_run", "finished", "replaced_reservation"]
)
def test_selection_rechecks_capacity_snapshot_before_reserving(w, monkeypatch, interleaving):
    from thomas.server import self_project_queue

    async def scenario():
        client = await _client(w)
        try:
            _room(monkeypatch)
            await post(client)
            self_project_queue.change(
                w.catalog,
                lambda data: data["queued"].append(self_project_queue.new_entry("Other ask", {}, "", client.port)),
            )
            await self_project_queue_tick.project_listing(client.app)
            if interleaving in {"finished", "replaced_reservation"}:
                self_project_queue.change(w.catalog, lambda data: data["queued"][1].update(starting={"pid": 1}))
                other_id = self_project_queue.read(w.catalog)["queued"][1]["id"]
                monkeypatch.setattr(self_project_queue_tick, "_in_flight", {other_id})
            slot = client.app["self_project_listing_slot"]

            def during_capacity_check(*_args):
                if interleaving == "dirty":
                    slot["dirty"] = True
                elif interleaving == "invalidated":
                    slot.update(dirty=False, invalidated=True)
                elif interleaving == "refreshed":
                    slot["snapshot"] = {**slot["snapshot"], "projects": [{"conversation_id": "new-start"}]}
                elif interleaving == "live_run":
                    monkeypatch.setattr(self_project_routes, "running_projects", lambda _app: {"new-build"})
                else:

                    def finish(data):
                        other = data["queued"].pop(1)
                        data["started"].insert(0, {**other, "conversation_id": "other-start"})
                        if interleaving == "replaced_reservation":
                            replacement = self_project_queue.new_entry("Replacement", {}, "", client.port)
                            replacement["starting"] = {"pid": 2}
                            data["queued"].append(replacement)

                    self_project_queue.change(w.catalog, finish)
                return None

            monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", during_capacity_check)
            selected = await asyncio.to_thread(
                self_project_queue_tick._select, w.catalog, client.app, client.port, time.time()
            )
            assert selected is None
            assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")
        finally:
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("during", ["listing", "capacity"])
def test_capacity_response_rechecks_queue_after_asynchronous_work(w, monkeypatch, during):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        _room(monkeypatch)
        client = await _client(w)
        snapshot = {"ok": True, "projects": [], "unreadable": []}
        slot = client.app["self_project_listing_slot"]
        slot["snapshot"] = snapshot

        def reserve():
            self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"pid": 2}))

        async def listing(_app):
            if during == "listing":
                reserve()
            return snapshot

        def capacity(_active, _now):
            if during == "capacity":
                reserve()
            return None

        try:
            await post(client)
            monkeypatch.setattr(self_project_queue_tick, "project_listing", listing)
            monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", capacity)
            result = await (await client.get(URL)).json()
            assert result["queued"][0]["starting"] == {"pid": 2}
            status = result["capacity"]
            if during == "listing":
                assert status["starting"] == 1
            else:
                assert status["running"] is None and status["blocked_by"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_dirty_snapshot_stays_incomplete_until_post_start_refresh_finishes(w, monkeypatch):
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
            slot = client.app["self_project_listing_slot"]
            slot["dirty"] = True
            # Begin the list page's post-start refresh before capacity/dispatch arrive.
            await client.get("/api/self/projects")
            assert await asyncio.to_thread(entered.wait, 2)
            capacity = (await (await asyncio.wait_for(client.get(URL), 1)).json())["capacity"]
            assert capacity["blocked_by"] == "Thomas projects could not all be read; try again after the list refreshes"
            await asyncio.wait_for(self_project_queue_tick.tick(client.app, w.catalog), 1)
            assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")
            release.set()
            await asyncio.wait_for(slot["task"], 5)
            assert not self_project_queue_tick._cached_listing(client.app).get("unreadable")
        finally:
            release.set()
            slot = client.app["self_project_listing_slot"]
            if slot.get("task"):
                await asyncio.wait_for(slot["task"], 5)
            await client.close()

    asyncio.run(scenario())
