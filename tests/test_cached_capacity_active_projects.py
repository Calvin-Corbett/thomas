"""Shared project snapshots still count work owned by another server."""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from tests.test_project_queue_cached_capacity import URL, _client, _room, w  # noqa: F401
from thomas.server import self_project_queue, self_project_queue_tick
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import self_project_routes


@pytest.mark.parametrize("selection", [False, True])
def test_capacity_includes_active_cached_projects_outside_local_running_set(w, monkeypatch, selection):
    self_project_queue.enqueue(w.catalog, "Wait for room", {}, "", 1)
    projects = [
        {"conversation_id": "local", "state": "running"},
        {"conversation_id": "remote", "state": "paused"},
        {"conversation_id": "repair", "state": "repair round 2"},
        {"conversation_id": "done", "state": "done"},
    ]
    app = {
        "self_project_listing_slot": {"snapshot": {"projects": projects, "unreadable": []}},
        APP_PRAXIS_START_CODE_RUN: object(),
    }
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    monkeypatch.setattr(self_project_routes, "running_projects", lambda _app: {"local", "not-listed-yet"})
    counted = []

    def blocker(active, now):
        counted.append(active)
        return "Full" if active >= 4 else None

    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", blocker)
    if selection:
        assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
        assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")
    else:
        status = self_project_queue_tick.queue_status(app, self_project_queue.read(w.catalog))
        assert status["blocked_by"] == "Full"
        assert status["running"] == 4
    assert counted == [4]


@pytest.mark.parametrize("change", ["dirty", "invalidated", "snapshot", "running"])
def test_status_rechecks_inventory_after_resource_io(w, monkeypatch, change):
    slot = {"snapshot": {"projects": [], "unreadable": []}}
    app = {"self_project_listing_slot": slot, APP_PRAXIS_START_CODE_RUN: object()}
    running = set()
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    monkeypatch.setattr(self_project_routes, "running_projects", lambda _app: running.copy())

    def blocker(active, now):
        if change == "snapshot":
            slot["snapshot"] = {"projects": [{"conversation_id": "peer", "state": "running"}], "unreadable": []}
        elif change == "running":
            running.add("local")
        else:
            slot[change] = True
        return None

    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", blocker)
    status = self_project_queue_tick.queue_status(app, self_project_queue.read(w.catalog))
    assert status["running"] is None
    assert status["blocked_by"]


def test_selection_waits_for_snapshot_after_a_peer_finishes_starting(w, monkeypatch):
    peer = self_project_queue.enqueue(w.catalog, "Peer start", {}, "", 1)
    self_project_queue.enqueue(w.catalog, "Wait for peer snapshot", {}, "", 1)
    captured_at = time.time()

    def finish(data):
        row = data["queued"].pop(0)
        data["started"].append({**row, "started_at": captured_at + 1, "conversation_id": "peer"})

    self_project_queue.change(w.catalog, finish)
    slot = {"snapshot": {"projects": [], "unreadable": []}, "captured_at": captured_at}
    app = {"self_project_listing_slot": slot, APP_PRAXIS_START_CODE_RUN: object()}
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    assert slot["dirty"]
    assert self_project_queue.read(w.catalog)["started"][0]["id"] == peer["id"]
    assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")


@pytest.mark.parametrize("change", ["peer_finished", "local_started_after_check"])
def test_queue_get_rejects_starts_missing_from_its_checked_inventory(w, monkeypatch, change):
    _room(monkeypatch)
    running = set()
    monkeypatch.setattr(self_project_routes, "running_projects", lambda _app: running.copy())

    async def scenario():
        client = await _client(w)
        slot = client.app["self_project_listing_slot"]
        captured_at = time.time()
        snapshot = {"ok": True, "projects": [], "unreadable": []}
        slot.update(snapshot=snapshot, captured_at=captured_at, updated=time.monotonic())
        if change == "peer_finished":
            self_project_queue.change(
                w.catalog,
                lambda data: data["started"].append(
                    {"id": "peer", "conversation_id": "peer", "started_at": captured_at + 1}
                ),
            )
        else:
            original = self_project_queue_tick.queue_status

            def status(app, data):
                result = original(app, data)
                assert result["running"] == 0 and not result["blocked_by"]
                running.add("new-local-start")
                return result

            monkeypatch.setattr(self_project_queue_tick, "queue_status", status)
        try:
            result = await (await client.get(URL)).json()
            assert result["capacity"]["running"] is None
            assert result["capacity"]["blocked_by"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_recovery_keeps_a_slow_start_owned_by_a_live_peer(w, monkeypatch):
    row = self_project_queue.enqueue(w.catalog, "Still starting on peer", {}, "", 1)
    reservation = {"at": 1, "pid": 42}
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting=reservation))
    monkeypatch.setattr(self_project_queue_tick.serve_instance_guard, "pid_alive", lambda pid: pid == 42)

    def unexpected_scan(*_):
        pytest.fail("a live peer's reservation is not interrupted")

    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", unexpected_scan)
    self_project_queue_tick._reconcile(w.catalog, 1, [], set(), captured_at=time.time())
    data = self_project_queue.read(w.catalog)
    assert data["queued"][0]["id"] == row["id"]
    assert data["queued"][0]["starting"] == reservation
    assert not data["given_up"]


def test_cancelled_local_start_is_recovered_without_waiting_for_server_exit(w, monkeypatch):
    row = self_project_queue.enqueue(w.catalog, "Cancelled locally", {}, "", 1)
    reserved_at = time.time() - self_project_queue_tick.START_GRACE_S - 1
    self_project_queue.change(
        w.catalog,
        lambda data: data["queued"][0].update(starting={"at": reserved_at, "pid": os.getpid()}),
    )
    monkeypatch.setattr(self_project_queue_tick.serve_instance_guard, "pid_alive", lambda _pid: True)
    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", lambda *_: {})
    entered = asyncio.Event()

    async def start(*_args, **_kwargs):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(self_project_queue_tick.thomas_project, "start_thomas_project", start)

    async def cancel_start():
        self_project_queue_tick._in_flight.add(row["id"])
        reserved = self_project_queue.read(w.catalog)["queued"][0]
        task = asyncio.create_task(self_project_queue_tick._start({}, w.catalog, reserved, 1))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_start())
    assert row["id"] not in self_project_queue_tick._in_flight
    assert self_project_queue.read(w.catalog)["queued"][0]["starting"]
    self_project_queue_tick._reconcile(w.catalog, 1, [], set(), captured_at=time.time())
    data = self_project_queue.read(w.catalog)
    assert not data["queued"]
    assert data["given_up"][0]["id"] == row["id"]
    assert "server stopped before this project registered a start" in data["given_up"][0]["reason"]


def test_recovery_records_known_start_while_another_start_needs_a_newer_snapshot(w, monkeypatch):
    known = self_project_queue.enqueue(w.catalog, "Known start", {}, "", 1)
    pending = self_project_queue.enqueue(w.catalog, "Unresolved start", {}, "", 1)
    self_project_queue.change(
        w.catalog,
        lambda data: [row.update(starting={"at": time.time(), "pid": 0}) for row in data["queued"]],
    )
    project = {"queue_id": known["id"], "conversation_id": "known", "execution_id": "run", "state": "running"}
    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", lambda *_: {known["id"]: project})
    self_project_queue_tick._reconcile(w.catalog, 1, [], set(), 0)
    data = self_project_queue.read(w.catalog)
    assert [row["id"] for row in data["started"]] == [known["id"]]
    assert [row["id"] for row in data["queued"]] == [pending["id"]]
    assert not data["given_up"]


@pytest.mark.parametrize(
    "invalid",
    ["failed", "incomplete", "unreadable", "dirty", "invalidated", "error", "slot_incomplete", "slot_unreadable"],
)
def test_invalid_recent_snapshot_cannot_expire_an_interrupted_reservation(w, monkeypatch, invalid):
    row = self_project_queue.enqueue(w.catalog, "Interrupted start", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": 1, "pid": 1}))
    report = {"ok": invalid != "failed", "projects": [], "unreadable": []}
    slot = {"snapshot": report, "captured_at": time.time()}
    if invalid == "incomplete":
        report["incomplete"] = True
    elif invalid == "unreadable":
        report["unreadable"] = ["unreadable-green"]
    elif invalid in {"dirty", "invalidated", "error"}:
        slot[invalid] = True
    elif invalid == "slot_incomplete":
        slot["incomplete"] = True
    elif invalid == "slot_unreadable":
        slot["unreadable"] = ["unreadable-green"]
    app = {"self_project_listing_slot": slot}
    monkeypatch.setattr(self_project_routes, "running_projects", lambda _app: set())
    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", lambda *_: {})
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    data = self_project_queue.read(w.catalog)
    assert data["queued"][0]["id"] == row["id"]
    assert data["queued"][0]["starting"] == {"at": 1, "pid": 1}
    assert not data["given_up"] and not data["started"]
    capacity = self_project_queue_tick.queue_status(app, data)
    assert capacity["running"] is None and "read" in capacity["blocked_by"]


@pytest.mark.parametrize("discovery", ["catalog", "greens", "incomplete"])
def test_recovery_cannot_admit_against_snapshot_missing_recovered_project(w, monkeypatch, discovery):
    interrupted = self_project_queue.enqueue(w.catalog, "Interrupted start", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": 1, "pid": 1}))
    self_project_queue.enqueue(w.catalog, "Wait for room", {}, "", 1)
    slot = {"snapshot": {"ok": True, "projects": [], "unreadable": []}}
    app = {"self_project_listing_slot": slot}
    _room(monkeypatch)
    monkeypatch.setenv("THOMAS_SELF_PROJECT_PARALLEL", "1")
    monkeypatch.setattr(self_project_routes, "running_projects", lambda _app: set())
    recovered = {
        "queue_id": interrupted["id"],
        "conversation_id": "remote",
        "execution_id": "remote-run",
        "state": "running",
    }
    monkeypatch.setattr(
        self_project_queue_tick,
        "_queue_conversations",
        lambda *_: {interrupted["id"]: recovered} if discovery == "catalog" else {},
    )
    monkeypatch.setattr(
        self_project_routes,
        "read_projects",
        lambda *_a, **_kw: {
            "ok": True,
            "projects": [recovered] if discovery == "greens" else [],
            "unreadable": ["unreadable-green"] if discovery == "incomplete" else [],
        },
    )
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    assert slot.get("dirty")
    assert not any(
        row.get("starting") for row in self_project_queue.read(w.catalog)["queued"] if row["id"] != interrupted["id"]
    )
