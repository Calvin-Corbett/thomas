"""Regression checks for shared queue capacity, recovery, and stored asks."""

from __future__ import annotations

import asyncio
import errno
import json

import pytest

from tests.test_a_self_project_queue import (  # noqa: F401 -- keep persistence in test data
    _client,
    _room,
    _warm_listing,
    isolated,
    post,
)
from tests.test_a_thomas_project_starts_without_chat import CLAUDE, w  # noqa: F401
from thomas.forge.anvil import forge_code_store
from thomas.server import autopilot_hold_tick, self_project_queue, self_project_queue_tick, thomas_project
from thomas.server.routes import self_project_routes


def test_negative_start_recovery_is_refreshed_before_retry(tmp_path, monkeypatch):
    from thomas.server import self_project_queue as store
    from thomas.server import self_project_queue_tick as tick

    row = {"id": "late", "tries": 1, "starting": {"port": 10, "pid": 123, "at": 1}}
    data = {"queued": [row], "started": [], "given_up": []}
    monkeypatch.setattr(store, "read", lambda catalog: data)
    monkeypatch.setattr(store, "change", lambda catalog, update: update(data))
    monkeypatch.setattr(tick.serve_instance_guard, "pid_alive", lambda pid: False)
    now = [2.0]
    monkeypatch.setattr(tick.time, "time", lambda: now[0])
    records = {}
    monkeypatch.setattr(tick, "_queue_conversations", lambda *args: dict(records))
    recovery = {}
    tick._reconcile(tmp_path, 10, [], set(), captured_at=2, recovery=recovery)
    assert data["queued"] and not data["given_up"]
    records["late"] = {"conversation_id": "registered", "queue_id": "late", "execution_id": "green"}
    now[0] += tick.START_GRACE_S + 1
    tick._reconcile(tmp_path, 10, [], set(), captured_at=now[0], recovery=recovery)
    assert data["started"][0]["conversation_id"] == "registered"
    assert not data["queued"] and not data["given_up"]


@pytest.fixture(autouse=True)
def caged_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")


def test_handed_in_catalog_conversation_does_not_restart(w, monkeypatch):
    async def scenario():
        client = await _client(w)
        try:
            ask = await post(client)
            self_project_queue.change(
                w.catalog,
                lambda data: data["queued"][0].update(starting={"pid": -1, "at": 1}),
            )
            project = {"queue_id": ask["id"], "execution_id": "gone"}
            conversation = forge_code_store.new_conversation(w.catalog, title="handed", thomas_project=project)
            forge_code_store._write_conversation(w.catalog, conversation)
            monkeypatch.setattr(autopilot_hold_tick, "port_of", lambda app: client.port)
            _room(monkeypatch)
            calls = []

            async def start(app, **kwargs):
                calls.append(kwargs)

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            await self_project_queue_tick.tick(client.app, w.catalog)
            await asyncio.sleep(0)
            assert not calls
            assert self_project_queue.read(w.catalog)["started"][0]["id"] == ask["id"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_two_ports_share_last_slot(w, monkeypatch):
    async def scenario():
        first, second = await _client(w), await _client(w)
        try:
            other = self_project_queue.enqueue(w.catalog, "other port", CLAUDE, "", second.port)
            await post(first)
            # Simulate an abandoned reservation with a deterministically dead PID.
            self_project_queue.change(
                w.catalog,
                lambda data: next(row for row in data["queued"] if row["id"] == other["id"]).update(
                    starting={"pid": -1, "at": 1}
                ),
            )
            _room(monkeypatch, rows=[{"state": "running"}] * 3)
            monkeypatch.setattr(autopilot_hold_tick, "port_of", lambda app: first.port)
            calls = []

            async def start(app, **kwargs):
                calls.append(kwargs)
                return {"conversation_id": "c", "execution_id": "e"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            await self_project_queue_tick.tick(first.app, w.catalog)
            await asyncio.sleep(0.05)
            data = self_project_queue.read(w.catalog)
            assert len(calls) == 1
            assert calls[0]["meta"]["queue_id"] != other["id"]
            assert data["started"][0]["id"] == calls[0]["meta"]["queue_id"]
            assert not any(row["id"] == other["id"] for row in data["queued"])
            assert data["given_up"][0]["id"] == other["id"]
            assert "server stopped before this project registered" in data["given_up"][0]["reason"]
        finally:
            await first.close()
            await second.close()

    asyncio.run(scenario())


def test_new_failure_discards_a_previous_permission_blocker(w):
    from thomas.server import self_project_queue as store
    from thomas.server import self_project_queue_tick as queue

    entry = store.enqueue(w.catalog, "repair", {}, "", 1)
    store.change(
        w.catalog,
        lambda data: data["queued"][0].update(start_blocker={"kind": "permission", "path": str(w.catalog)}),
    )
    queue._failed(w.catalog, entry["id"], "Build is busy")
    assert "start_blocker" not in store.read(w.catalog)["queued"][0]


@pytest.mark.parametrize("interrupted", [False, True])
def test_legacy_transient_recovery_preserves_one_probe_budget(interrupted):
    from thomas.server import self_project_queue_tick as queue

    row = {
        "id": "legacy",
        "tries": queue.MAX_START_TRIES,
        "given_up": True,
        "failed_at": 100,
        "reason": "Build is busy",
    }
    if interrupted:
        row.update(
            reason="The server stopped before this project registered a start. It will retry.",
            last_reason="Build is busy",
            recovery_probes=1,
        )
    data = {"queued": [], "given_up": [row]}
    queue._retry_failures(data, [], 100 + queue.RETRY_AFTER_S * (4 if interrupted else 2))
    assert data["given_up"] == []
    assert data["queued"][0]["tries"] == queue.MAX_START_TRIES - 1
    assert not data["queued"][0].get("given_up")
    assert data["queued"][0]["recovery_probes"] == (2 if interrupted else 1)


@pytest.mark.parametrize("missing_last_tried_at", [False, True])
@pytest.mark.parametrize(
    "reason",
    [
        "Build is busy",
        "Project start refused: preparation exceeded 8 seconds. Try again.",
        "Project start refused: preparation stalled -- nothing moved for 30 seconds while copying Thomas's source. Try again.",
        OSError(errno.EAGAIN, "Resource temporarily unavailable"),
        OSError(errno.ENOMEM, "Cannot allocate memory"),
        OSError(errno.EMFILE, "Too many open files"),
        TimeoutError("Preparation deadline elapsed"),
    ],
)
@pytest.mark.parametrize("legacy_notice", [False, True])
def test_exhausted_transient_start_recovers_through_ticks(w, monkeypatch, reason, legacy_notice, missing_last_tried_at):
    from thomas.server import self_project_queue as store
    from thomas.server import self_project_queue_tick as queue

    async def scenario():
        monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
        _room(monkeypatch)
        client = await _client(w)
        try:
            monkeypatch.setattr(queue.autopilot_hold_tick, "port_of", lambda app: client.port)
            clock = [10000.0]
            monkeypatch.setattr(queue.time, "time", lambda: clock[0])
            calls = []
            blocked = True

            async def start_project(*args, **kwargs):
                calls.append(clock[0])
                if blocked:
                    if isinstance(reason, Exception):
                        raise reason
                    raise thomas_project.ThomasProjectError(reason)
                return {"conversation_id": "recovered", "execution_id": "recovered-run"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start_project)
            queued = await post(client)

            async def tick():
                await _warm_listing(client.app)
                await queue.tick(client.app, w.catalog)
                if queue._start_tasks:
                    await asyncio.wait_for(asyncio.gather(*tuple(queue._start_tasks)), 5)

            for attempt in range(queue.MAX_START_TRIES):
                await tick()
                assert len(calls) == attempt + 1
                if attempt < queue.MAX_START_TRIES - 1:
                    clock[0] += queue.RETRY_AFTER_S
            row = store.read(w.catalog)["queued"][0]
            assert row["given_up"] and row["failed_at"] == clock[0]
            exhausted_at = clock[0]
            if missing_last_tried_at:
                store.change(w.catalog, lambda data: data["queued"][0].pop("last_tried_at", None))
            if legacy_notice:

                def move_to_notices(data):
                    row = data["queued"].pop()
                    row["reason"] = row.pop("last_reason")
                    data["given_up"].append(row)

                store.change(w.catalog, move_to_notices)
            clock[0] += queue.RETRY_AFTER_S
            await tick()
            assert len(calls) == queue.MAX_START_TRIES
            clock[0] = exhausted_at + 2 * queue.RETRY_AFTER_S
            await tick()
            assert len(calls) == queue.MAX_START_TRIES + 1
            row = store.read(w.catalog)["queued"][0]
            assert row["given_up"] and row["tries"] == queue.MAX_START_TRIES
            assert row["failed_at"] == clock[0] and row["last_reason"] == str(reason)
            probe_at = clock[0]
            # Restarted workers read the persisted backoff instead of granting a new batch.
            for _ in range(3):
                clock[0] += queue.RETRY_AFTER_S
                await tick()
            assert len(calls) == queue.MAX_START_TRIES + 1
            blocked = False
            clock[0] = probe_at + 4 * queue.RETRY_AFTER_S
            await tick()
            data = store.read(w.catalog)
            assert len(calls) == queue.MAX_START_TRIES + 2
            assert not data["queued"] and not data["given_up"]
            assert data["started"][0]["id"] == queued["id"]
            assert not any(
                key in data["started"][0]
                for key in ("failed_at", "last_reason", "start_blocker", "recovery_probes", "given_up")
            )
            response = await (await client.get("/api/self/projects/queue")).json()
            assert not response["queued"] and not response["given_up"]
        finally:
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "error",
    [
        ValueError("Invalid project settings"),
        OSError(errno.EINVAL, "Invalid preparation timeout setting"),
        FileNotFoundError(errno.ENOENT, "Required source is missing"),
    ],
)
def test_permanent_start_errors_do_not_get_transient_probes(w, monkeypatch, error):
    queue = self_project_queue_tick
    clock = [10_000.0]
    monkeypatch.setattr(queue.time, "time", lambda: clock[0])
    entry = self_project_queue.enqueue(w.catalog, "repair", {}, "", 1)
    blocker = queue._start_blocker(error)
    for _ in range(queue.MAX_START_TRIES):
        queue._failed(w.catalog, entry["id"], str(error), blocker)
        clock[0] += queue.RETRY_AFTER_S
    clock[0] += 86_400
    data = self_project_queue.read(w.catalog)
    queue._retry_failures(data, [], clock[0])
    row = data["queued"][0]
    assert row["given_up"] and row["tries"] == queue.MAX_START_TRIES
    assert data["queued"][0]["id"] == entry["id"]
    assert not queue._transient_probe_due(row, clock[0])


def test_running_start_is_not_counted_twice(w, monkeypatch):
    async def scenario():
        client = await _client(w)
        try:
            running = self_project_queue.enqueue(w.catalog, "already running", CLAUDE, "", client.port + 1)
            ask = await post(client)
            self_project_queue.change(
                w.catalog,
                lambda data: next(row for row in data["queued"] if row["id"] == running["id"]).update(
                    starting={"pid": 12345, "at": 1}
                ),
            )
            conversation = forge_code_store.new_conversation(
                w.catalog,
                title="already running",
                thomas_project={"queue_id": running["id"], "execution_id": "green"},
            )
            forge_code_store._write_conversation(w.catalog, conversation)
            _room(
                monkeypatch,
                rows=[{"state": "running", "conversation_id": conversation["id"]}] + [{"state": "running"}] * 2,
            )
            monkeypatch.setattr(autopilot_hold_tick, "port_of", lambda app: client.port)
            calls = []

            async def start(app, **kwargs):
                calls.append(kwargs)
                return {"conversation_id": "new", "execution_id": "new"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            await self_project_queue_tick.tick(client.app, w.catalog)
            await asyncio.sleep(0.05)
            assert len(calls) == 1
            assert calls[0]["meta"]["queue_id"] == ask["id"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_stored_overlong_request_is_refused(w, monkeypatch):
    async def scenario():
        client = await _client(w)
        try:
            ask = await post(client)
            file = self_project_queue.path(w.catalog)
            data = self_project_queue.read(w.catalog)
            data["queued"][0]["request"] = "x" * (self_project_routes._REQUEST_MAX_CHARS + 1)
            file.write_text(json.dumps(data), encoding="utf-8")
            monkeypatch.setattr(autopilot_hold_tick, "port_of", lambda app: client.port)
            _room(monkeypatch)
            calls = []

            async def start(app, **kwargs):
                calls.append(kwargs)

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            await self_project_queue_tick.tick(client.app, w.catalog)
            assert not calls
            data = self_project_queue.read(w.catalog)
            assert data["given_up"][0]["id"] == ask["id"]
            assert (
                data["given_up"][0]["reason"]
                == f"request is longer than {self_project_routes._REQUEST_MAX_CHARS} characters"
            )
        finally:
            await client.close()

    asyncio.run(scenario())
