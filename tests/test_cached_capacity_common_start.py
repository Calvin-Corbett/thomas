"""Every successful local start invalidates cached admission, not only HTTP and queue starts."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from tests.test_a_thomas_project_has_a_team_and_lands_by_card import (
    _stub_create_green,
    blue,  # noqa: F401 -- fixture
)
from tests.test_project_queue_cached_capacity import _room, w  # noqa: F401 -- fixture
from thomas.server import green_checkout, self_project_queue, self_project_queue_tick, thomas_project
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import self_project_routes
from thomas.server.routes.self_project_listing_cache import read_listing


@pytest.fixture
def inherited_persistence(tmp_path, monkeypatch):
    from thomas.core import persistence

    inherited = persistence.PersistenceEngine(tmp_path / "inherited.json")
    monkeypatch.setattr(persistence, "_DEFAULT_STATE_FILE", inherited.state_file)
    monkeypatch.setattr(persistence, "_engine", inherited)
    return inherited


@pytest.mark.parametrize("server_fixture", ["start", "refusal", "listing", "chat"])
def test_server_fixture_replaces_inherited_persistence(inherited_persistence, tmp_path, monkeypatch, server_fixture):
    from tests import test_a_dead_thomas_project_is_not_listed_as_running as listing_tests
    from tests import test_a_refusal_that_clears_hands_in_again as refusal_tests
    from tests import test_a_thomas_project_starts_without_chat as start_tests
    from tests import test_you_see_your_self_change_projects_in_chat as chat_tests
    from thomas.core import persistence

    fixture = {
        "start": start_tests.w,
        "refusal": refusal_tests.isolated_persistence,
        "listing": listing_tests.w,
        "chat": chat_tests.isolated_persistence,
    }[server_fixture]
    fixture.__wrapped__(tmp_path, monkeypatch)
    engine = persistence.get_persistence()
    assert engine is not inherited_persistence
    assert engine.state_file != inherited_persistence.state_file
    assert engine.state_file == persistence._DEFAULT_STATE_FILE


@pytest.mark.parametrize("refresh_in_flight", [False, True])
def test_common_start_invalidates_capacity_until_paused_project_is_in_snapshot(
    tmp_path, monkeypatch, blue, w, refresh_in_flight
):
    _room(monkeypatch)
    monkeypatch.setattr(green_checkout, "create_green", _stub_create_green(tmp_path, []))
    monkeypatch.setattr(self_project_routes, "running_projects", lambda _app: set())
    self_project_queue.enqueue(w.catalog, "Next project", {}, "", 1)
    entered, release = threading.Event(), threading.Event()
    paused = []
    calls = 0

    def listing(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1 and refresh_in_flight:
            entered.set()
            assert release.wait(5)
            return {"ok": True, "projects": [], "unreadable": []}
        return {"ok": True, "projects": list(paused), "unreadable": []}

    monkeypatch.setattr(self_project_routes, "read_projects", listing)

    async def start(body, *, port):
        paused.append({"conversation_id": body["conversation_id"], "state": "paused"})
        return 200, {"ok": True}

    async def scenario():
        slot = {
            "snapshot": {"ok": True, "projects": [], "unreadable": []},
            "updated": time.monotonic() - (3 if refresh_in_flight else 0),
            "captured_at": time.time(),
        }
        app = {"self_project_listing_slot": slot, APP_PRAXIS_START_CODE_RUN: start}
        try:
            if refresh_in_flight:
                await read_listing(slot, w.catalog, lambda: set(), listing)
                assert await asyncio.to_thread(entered.wait, 2)
            await thomas_project.start_thomas_project(app, request="Chat project", settings={}, port=1)
            status = self_project_queue_tick.queue_status(app, self_project_queue.read(w.catalog))
            assert status["running"] is None and status["blocked_by"]
            assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
            assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")
            if refresh_in_flight:
                release.set()
                await slot["task"]
                assert calls >= 2
            await read_listing(slot, w.catalog, lambda: set(), listing)
            await slot["task"]
            status = self_project_queue_tick.queue_status(app, self_project_queue.read(w.catalog))
            assert status["running"] == 1
            assert not status["blocked_by"]
        finally:
            release.set()
            if slot.get("task"):
                await slot["task"]

    asyncio.run(scenario())


def test_a_real_post_start_refresh_discovers_the_new_project(tmp_path, monkeypatch, blue, w):
    def create(*, blue, execution_id):
        work = tmp_path / "work" / execution_id
        (work / ".git").mkdir(parents=True)
        return green_checkout.Green(execution_id, work, tmp_path / "git" / execution_id, "deadbeef", blue)

    monkeypatch.setattr(green_checkout, "create_green", create)
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path)
    reader = self_project_routes.read_projects
    _room(monkeypatch)
    monkeypatch.setattr(self_project_routes, "read_projects", reader)
    self_project_queue.enqueue(w.catalog, "Next project", {}, "", 1)

    async def scenario():
        async def build(*_args, **_kwargs):
            return 200, {"ok": True}

        slot = {}
        app = {"self_project_listing_slot": slot, APP_PRAXIS_START_CODE_RUN: build}
        await read_listing(slot, w.catalog, lambda: set(), self_project_routes.read_projects)
        await slot["task"]
        assert not slot["snapshot"]["projects"]
        result = await thomas_project.start_thomas_project(app, request="New project", settings={}, port=1)
        app["test_running"] = {result["conversation_id"]}
        assert self_project_queue_tick.queue_status(app, self_project_queue.read(w.catalog))["running"] is None
        await read_listing(slot, w.catalog, lambda: app["test_running"], self_project_routes.read_projects)
        await slot["task"]
        assert not slot["snapshot"]["unreadable"]
        assert [row["conversation_id"] for row in slot["snapshot"]["projects"]] == [result["conversation_id"]]
        status = self_project_queue_tick.queue_status(app, self_project_queue.read(w.catalog))
        assert status["running"] == 1 and not status["blocked_by"]

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["checkout", "build"])
@pytest.mark.parametrize("outcome", ["success", "refusal", "cancel"])
def test_common_start_reserves_capacity_across_awaits_and_releases_on_exit(
    tmp_path, monkeypatch, blue, w, stage, outcome
):
    from thomas.server import thomas_project_start

    _room(monkeypatch)
    create = _stub_create_green(tmp_path, [])
    monkeypatch.setattr(green_checkout, "create_green", create)
    monkeypatch.setattr(self_project_routes, "running_projects", lambda _app: set())
    monkeypatch.setattr(
        self_project_routes, "read_projects", lambda *_args: {"ok": True, "projects": [], "unreadable": []}
    )
    self_project_queue.enqueue(w.catalog, "Next project", {}, "", 1)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        original_create = thomas_project_start._create_green

        async def wait_here():
            entered.set()
            await release.wait()

        async def checkout(*args):
            if stage == "checkout":
                await wait_here()
            return await original_create(*args)

        async def build(_body, *, port):
            if stage == "build":
                await wait_here()
            return (503, {"error": "refused"}) if outcome == "refusal" else (200, {"ok": True})

        monkeypatch.setattr(thomas_project_start, "_create_green", checkout)
        slot = {
            "snapshot": {"ok": True, "projects": [], "unreadable": []},
            "captured_at": time.time(),
            "updated": time.monotonic(),
        }
        app = {"self_project_listing_slot": slot, APP_PRAXIS_START_CODE_RUN: build}
        task = asyncio.create_task(thomas_project.start_thomas_project(app, request="Direct", settings={}, port=1))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            # Even a completed refresh during an unrecorded start cannot free admission.
            await read_listing(slot, w.catalog, lambda: set(), self_project_routes.read_projects)
            await slot["task"]
            status = self_project_queue_tick.queue_status(app, self_project_queue.read(w.catalog))
            assert status["running"] is None and status["blocked_by"]
            assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
            assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")
            if outcome == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                release.set()
                if outcome == "refusal":
                    with pytest.raises(thomas_project.ThomasProjectError, match="refused"):
                        await task
                else:
                    await task
            assert slot["pending_starts"] == 0 and slot["dirty"]
            await read_listing(slot, w.catalog, lambda: set(), self_project_routes.read_projects)
            await slot["task"]
            status = self_project_queue_tick.queue_status(app, self_project_queue.read(w.catalog))
            assert status["running"] == 0 and not status["blocked_by"]
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if slot.get("task"):
                await slot["task"]

    asyncio.run(scenario())
