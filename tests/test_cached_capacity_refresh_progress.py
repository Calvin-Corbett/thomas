"""Recovery requests must let the shared project refresh finish."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from tests.test_project_queue_cached_capacity import URL, _client, _room, w  # noqa: F401
from thomas.server import self_project_queue, self_project_queue_tick, thomas_project
from thomas.server.routes import self_project_listing_cache, self_project_routes


def test_peer_start_does_not_repeatedly_invalidate_a_running_refresh(w, monkeypatch):
    async def scenario():
        _room(monkeypatch)
        client = await _client(w)
        entered, release = threading.Event(), threading.Event()
        calls = []
        captured_at = time.time() - 10
        peer = self_project_queue.enqueue(w.catalog, "Peer start", {}, "", client.port)
        self_project_queue.enqueue(w.catalog, "Next start", {}, "", client.port)
        self_project_queue_tick._finish(w.catalog, peer["id"], {"conversation_id": "peer", "execution_id": "run"})
        slot = client.app["self_project_listing_slot"]
        slot.update(snapshot={"projects": [], "unreadable": []}, captured_at=captured_at)

        def read(*_):
            calls.append(1)
            entered.set()
            assert release.wait(5)
            return {"projects": [{"conversation_id": "peer", "state": "done"}], "unreadable": []}

        monkeypatch.setattr(self_project_routes, "read_projects", read)
        try:
            # Start an ordinary stale-while-refresh scan before noticing the peer.
            await self_project_queue_tick.project_listing(client.app)
            assert await asyncio.to_thread(entered.wait, 2)
            for _ in range(3):
                assert (
                    await asyncio.to_thread(
                        self_project_queue_tick._select, w.catalog, client.app, client.port, time.time()
                    )
                    is None
                )
                assert not slot.get("dirty"), "a running refresh must not be invalidated by each tick"
            release.set()
            await asyncio.wait_for(slot["task"], 5)
            assert len(calls) == 1
            assert slot["snapshot"]["projects"][0]["conversation_id"] == "peer"
        finally:
            release.set()
            if slot.get("task"):
                await asyncio.wait_for(slot["task"], 5)
            await client.close()

    asyncio.run(scenario())


def test_confirmed_absent_interrupted_start_does_not_request_another_scan(w, monkeypatch):
    _room(monkeypatch)
    interrupted = self_project_queue.enqueue(w.catalog, "Interrupted", {}, "", 1)
    self_project_queue.enqueue(w.catalog, "Next", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": 1, "pid": 0}))
    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", lambda *_: {})
    active, refresh_needed = self_project_queue_tick._reconcile(w.catalog, 1, [], set(), time.time())
    assert not active
    assert not refresh_needed
    data = self_project_queue.read(w.catalog)
    assert data["given_up"][0]["id"] == interrupted["id"]
    assert len(data["queued"]) == 1


def test_refresh_publication_cannot_age_an_older_snapshot_during_recovery(w, monkeypatch):
    _room(monkeypatch)
    interrupted = self_project_queue.enqueue(w.catalog, "Interrupted", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": 1, "pid": 0}))
    slot = {"snapshot": {"projects": [], "unreadable": []}, "captured_at": 1}
    app = {"self_project_listing_slot": slot}
    monkeypatch.setattr(self_project_routes, "running_projects", lambda *_: set())
    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", lambda *_: {})
    cached_listing = self_project_queue_tick._cached_listing
    project = {
        "conversation_id": "green-only",
        "execution_id": "green-run",
        "queue_id": interrupted["id"],
        "state": "running",
    }

    def publish_after_read(app):
        old_listing = cached_listing(app)
        slot.update(snapshot={"projects": [project], "unreadable": []}, captured_at=time.time())
        return old_listing

    monkeypatch.setattr(self_project_queue_tick, "_cached_listing", publish_after_read)
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    data = self_project_queue.read(w.catalog)
    assert not data["given_up"], "a newer capture time cannot prove absence from an older listing"
    assert data["queued"][0]["starting"]
    monkeypatch.setattr(self_project_queue_tick, "_cached_listing", cached_listing)
    slot["dirty"] = False
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    data = self_project_queue.read(w.catalog)
    assert not data["given_up"] and not data["queued"]
    assert data["started"][0]["conversation_id"] == "green-only"


def test_refresh_publication_cannot_validate_superseded_rows(w, monkeypatch):
    _room(monkeypatch)
    self_project_queue.enqueue(w.catalog, "Next", {}, "", 1)
    stale = {"projects": [], "unreadable": []}
    replacement = {"projects": [{"conversation_id": "peer", "state": "running"}], "unreadable": []}

    class PublishingSlot(dict):
        def get(self, key, default=None):
            value = super().get(key, default)
            if key == "snapshot" and value is stale:
                # Publish between the worker's snapshot read and its validity checks.
                self.update(snapshot=replacement, invalidated=False, captured_at=time.time())
            return value

    slot = PublishingSlot(snapshot=stale, invalidated=True, captured_at=1)
    app = {"self_project_listing_slot": slot}
    monkeypatch.setattr(self_project_routes, "running_projects", lambda *_: set())
    counts = []
    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", lambda count, now: counts.append(count))
    status = self_project_queue_tick.queue_status(app, self_project_queue.read(w.catalog))
    assert status["running"] is None, "superseded rows must not authorize capacity"
    assert status["blocked_by"]
    assert not counts

    slot.update(snapshot=stale, invalidated=True)
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")
    assert not counts


def test_recovery_keeps_reservation_if_snapshot_changes_during_catalog_read(w, monkeypatch):
    _room(monkeypatch)
    row = self_project_queue.enqueue(w.catalog, "Interrupted", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": 1, "pid": 1}))
    old = {"projects": [], "unreadable": []}
    project = {"conversation_id": "green-only", "execution_id": "run", "queue_id": row["id"], "state": "running"}
    slot = {"snapshot": old, "captured_at": time.time()}
    app = {"queue_test_port": 1, "self_project_listing_slot": slot}
    monkeypatch.setattr(self_project_queue_tick.serve_instance_guard, "pid_alive", lambda *_: False)

    def publish(_catalog, _wanted):
        slot.update(snapshot={"projects": [project], "unreadable": []}, captured_at=time.time())
        return {}

    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", publish)
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    data = self_project_queue.read(w.catalog)
    assert not data["given_up"] and not data["started"]
    assert data["queued"][0]["starting"]
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    data = self_project_queue.read(w.catalog)
    assert not data["given_up"] and not data["queued"]
    assert data["started"][0]["conversation_id"] == "green-only"


def test_selection_rechecks_snapshot_after_capacity_ledger_read(w, monkeypatch):
    _room(monkeypatch)
    self_project_queue.enqueue(w.catalog, "Next", {}, "", 1)
    original = {"projects": [], "unreadable": []}
    replacement = {"projects": [{"conversation_id": "peer", "state": "running"}], "unreadable": []}
    slot = {"snapshot": original, "captured_at": time.time()}
    app = {"self_project_listing_slot": slot}
    monkeypatch.setattr(self_project_routes, "running_projects", lambda *_: set())
    counts = []

    def publish_during_capacity_check(count, now):
        counts.append(count)
        slot.update(snapshot=replacement, captured_at=time.time())
        return None

    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", publish_during_capacity_check)
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    assert counts == [0]
    assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")

    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", lambda count, now: counts.append(count))
    selected = self_project_queue_tick._select(w.catalog, app, 1, time.time())
    assert selected is not None and selected["starting"]
    assert counts == [0, 1]


def test_recovery_reuses_catalog_read_until_snapshot_or_reservation_changes(w, monkeypatch):
    _room(monkeypatch)
    row = self_project_queue.enqueue(w.catalog, "Interrupted", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": time.time(), "pid": 1}))
    slot = {"snapshot": {"projects": [], "unreadable": []}, "captured_at": time.time()}
    app = {"self_project_listing_slot": slot}
    monkeypatch.setattr(self_project_routes, "running_projects", lambda *_: set())
    monkeypatch.setattr(self_project_queue_tick.serve_instance_guard, "pid_alive", lambda *_: False)
    scans = []
    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", lambda _, wanted: scans.append(wanted) or {})

    for _ in range(2):
        assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    assert scans == [{row["id"]}]

    slot.update(snapshot={"projects": [], "unreadable": []}, captured_at=time.time())
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    assert len(scans) == 2
    self_project_queue.change(w.catalog, lambda data: data["queued"][0]["starting"].update(at=time.time() + 1))
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    assert len(scans) == 3
    assert self_project_queue.read(w.catalog)["queued"][0]["starting"]


def test_recovery_reuses_live_fallback_until_snapshot_or_reservation_changes(w, monkeypatch):
    _room(monkeypatch)
    row = self_project_queue.enqueue(w.catalog, "Interrupted", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": time.time(), "pid": 1}))
    projects = [{"conversation_id": "unresolved", "execution_id": "run", "state": "stopped"}]
    slot = {"snapshot": {"projects": projects, "unreadable": []}, "captured_at": time.time()}
    app = {"self_project_listing_slot": slot}
    monkeypatch.setattr(self_project_routes, "running_projects", lambda *_: set())
    monkeypatch.setattr(self_project_queue_tick.serve_instance_guard, "pid_alive", lambda *_: False)
    monkeypatch.setattr(self_project_queue_tick, "_queue_conversations", lambda *_: {})
    reads = []
    monkeypatch.setattr(thomas_project, "_read_live", lambda *args: reads.append(args) or None)

    for _ in range(3):
        assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    assert len(reads) == 1

    slot.update(snapshot={"projects": projects, "unreadable": []}, captured_at=time.time())
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    assert len(reads) == 2
    self_project_queue.change(w.catalog, lambda data: data["queued"][0]["starting"].update(at=time.time() + 1))
    assert self_project_queue_tick._select(w.catalog, app, 1, time.time()) is None
    assert len(reads) == 3
    assert self_project_queue.read(w.catalog)["queued"][0]["starting"]


def test_peer_reservation_already_in_snapshot_is_not_counted_twice(w, monkeypatch):
    row = self_project_queue.enqueue(w.catalog, "Peer", {}, "", 1)
    self_project_queue.change(w.catalog, lambda data: data["queued"][0].update(starting={"at": 1, "pid": 1}))
    project = {"conversation_id": "peer", "queue_id": row["id"], "state": "running"}
    app = {"queue_test_port": 1, "self_project_listing_slot": {"snapshot": {"projects": [project], "unreadable": []}}}
    monkeypatch.setattr(self_project_routes, "running_projects", lambda *_: set())
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    app[self_project_queue_tick.APP_PRAXIS_START_CODE_RUN] = w.hook
    counts = []
    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", lambda count, now: counts.append(count))
    status = self_project_queue_tick.queue_status(app, self_project_queue.read(w.catalog))
    assert status["running"] == 1 and status["starting"] == 1
    assert counts == [1]


@pytest.mark.parametrize("project_count", [20, 200])
@pytest.mark.parametrize("expiry_consumer", ["listing", "capacity", "starter"])
def test_sequential_routes_and_starter_share_snapshot_until_ttl_expires(w, monkeypatch, project_count, expiry_consumer):
    from thomas.server.routes import self_project_listing_cache as cache

    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(cache, "time", SimpleNamespace(monotonic=lambda: clock.now, time=time.time))
    _room(monkeypatch)
    projects = [{"conversation_id": f"peer-{n}", "state": "running"} for n in range(project_count)]
    calls = []

    def reader(*_args, **_kwargs):
        calls.append(clock.now)
        return {"ok": True, "projects": projects, "unreadable": []}

    monkeypatch.setattr(self_project_routes, "read_projects", reader)
    monkeypatch.setattr(
        self_project_queue_tick, "capacity_blocker", lambda count, _now: "No room" if count >= project_count else None
    )

    async def scenario():
        client = await _client(w)
        client.app["queue_test_port"] = client.port
        self_project_queue.enqueue(w.catalog, "Waiting for room", {}, "", client.port)
        try:
            first = await (await client.get("/api/self/projects")).json()
            assert first["projects"] == projects and not first["refreshing"]
            slot = client.app["self_project_listing_slot"]
            initial_task = slot["task"]
            for _ in range(3):
                clock.now += 0.1
                listing = await (await client.get("/api/self/projects")).json()
                status = await (await client.get(URL)).json()
                await self_project_queue_tick.tick(client.app, w.catalog)
                assert listing["projects"] == projects and not listing["refreshing"]
                assert status["capacity"]["running"] == project_count
                assert status["capacity"]["blocked_by"]
                assert slot["task"] is initial_task
                assert calls == [100.0]
            clock.now = 102.1
            if expiry_consumer == "starter":
                await self_project_queue_tick.tick(client.app, w.catalog)
            else:
                url = URL if expiry_consumer == "capacity" else "/api/self/projects"
                await (await client.get(url)).json()
            assert slot["task"] is not initial_task
            await asyncio.wait_for(slot["task"], 2)
            assert calls == [100.0, 102.1]
            fresh = await (await client.get("/api/self/projects")).json()
            assert not fresh["refreshing"] and len(calls) == 2
        finally:
            slot = client.app.get("self_project_listing_slot", {})
            if slot.get("task"):
                await asyncio.wait_for(slot["task"], 2)
            await client.close()

    asyncio.run(scenario())


def test_start_during_scan_cannot_be_older_than_its_snapshot(w, monkeypatch):
    _room(monkeypatch)
    clock = SimpleNamespace(now=time.time())
    monkeypatch.setattr(
        self_project_listing_cache, "time", SimpleNamespace(monotonic=time.monotonic, time=lambda: clock.now)
    )
    queued = self_project_queue.enqueue(w.catalog, "Waiting", {}, "", 1234)
    scan_started = clock.now

    def reader(*_args, **_kwargs):
        clock.now += 1
        self_project_queue.change(
            w.catalog,
            lambda data: data["started"].append(
                {"id": "concurrent", "conversation_id": "missed-by-scan", "started_at": clock.now}
            ),
        )
        clock.now += 1
        return {"ok": True, "projects": [], "unreadable": []}

    monkeypatch.setattr(self_project_routes, "read_projects", reader)
    app = {"self_project_listing_slot": {}}

    async def refresh():
        await self_project_queue_tick.project_listing(app)
        await asyncio.wait_for(app["self_project_listing_slot"]["task"], 3)

    asyncio.run(refresh())
    assert app["self_project_listing_slot"]["captured_at"] == scan_started
    assert self_project_queue_tick._select(w.catalog, app, 1234, time.time()) is None
    row = self_project_queue.read(w.catalog)["queued"][0]
    assert row["id"] == queued["id"] and not row.get("starting")
    assert app["self_project_listing_slot"]["dirty"]


@pytest.mark.parametrize("failure", ["incomplete", "exception"])
@pytest.mark.parametrize("warm", [False, True])
def test_incomplete_inventory_recovers_through_routes_and_starter_after_retry(w, monkeypatch, warm, failure):
    from thomas.server.routes import self_project_listing_cache as cache

    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(cache, "time", SimpleNamespace(monotonic=lambda: clock.now, time=time.time))
    _room(monkeypatch)
    result = {"ok": True, "projects": [{"conversation_id": "old", "state": "stopped"}], "unreadable": []}
    calls = []
    failing = False

    def reader(*_args, **_kwargs):
        calls.append(clock.now)
        if failing and failure == "exception":
            raise OSError("temporarily inaccessible inventory")
        return result

    monkeypatch.setattr(self_project_routes, "read_projects", reader)
    counts = []
    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", lambda count, now: counts.append(count))

    async def scenario():
        nonlocal result, failing
        client = await _client(w)
        client.app["queue_test_port"] = client.port
        queued = self_project_queue.enqueue(w.catalog, "Next", {}, "", client.port)
        try:
            if warm:
                await (await client.get("/api/self/projects")).json()
                await asyncio.wait_for(client.app["self_project_listing_slot"]["task"], 2)
                clock.now += 2.1
            failing = True
            result = {"ok": True, "projects": [], "unreadable": ["temporarily inaccessible green"]}
            await (await client.get("/api/self/projects")).json()
            slot = client.app["self_project_listing_slot"]
            await asyncio.wait_for(slot["task"], 2)
            scan_count = len(calls)
            for _ in range(3):
                clock.now += 0.1
                listing = await (await client.get("/api/self/projects")).json()
                status = await (await client.get(URL)).json()
                await self_project_queue_tick.tick(client.app, w.catalog)
                if failure == "exception":
                    assert slot["error"]
                    assert listing["refreshing"] is warm
                    if not warm:
                        assert listing["ok"] is False
                else:
                    assert listing["incomplete"] and listing["refreshing"] is warm
                assert listing.get("projects", []) == ([{"conversation_id": "old", "state": "stopped"}] if warm else [])
                assert status["capacity"]["running"] is None and status["capacity"]["blocked_by"]
                assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")
                assert len(calls) == scan_count and not counts
            failing = False
            result = {"ok": True, "projects": [{"conversation_id": "new", "state": "stopped"}], "unreadable": []}
            clock.now += 2.1
            await (await client.get(URL)).json()
            await asyncio.wait_for(slot["task"], 2)
            fresh = await (await client.get("/api/self/projects")).json()
            assert fresh["projects"] == result["projects"] and not fresh["refreshing"]
            assert not any(slot.get(key) for key in ("incomplete", "preserved", "invalidated", "unreadable", "error"))
            status = await (await client.get(URL)).json()
            assert status["capacity"]["running"] == 0 and not status["capacity"]["blocked_by"]
            dispatched = []

            async def start(_app, _catalog, selected, _port):
                dispatched.append(selected)
                self_project_queue_tick._in_flight.discard(selected["id"])

            monkeypatch.setattr(self_project_queue_tick, "_start", start)
            await self_project_queue_tick.tick(client.app, w.catalog)
            tasks = list(self_project_queue_tick._start_tasks)
            if tasks:
                await asyncio.wait_for(asyncio.gather(*tasks), 2)
            assert len(dispatched) == 1
            assert dispatched[0]["id"] == queued["id"] and dispatched[0]["starting"]
            assert len(calls) == scan_count + 1
        finally:
            slot = client.app.get("self_project_listing_slot", {})
            if slot.get("task"):
                await asyncio.wait_for(slot["task"], 2)
            await client.close()

    asyncio.run(scenario())
