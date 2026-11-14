"""A due queue ask must not stall the server's event loop during disk and capacity checks."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from tests.test_project_queue_cached_capacity import _client, _room, post, w  # noqa: F401
from thomas.core import atomic_json, machine_capacity, persistence
from thomas.server import (
    autopilot_hold_tick,
    autopilot_park,
    capacity_ledger,
    self_project_queue,
    self_project_queue_tick,
    thomas_project,
)
from thomas.server.routes import self_project_routes


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, w) -> None:
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(persistence, "_DEFAULT_STATE_FILE", tmp_path / "data" / "thomas_state.json")
    monkeypatch.setattr(persistence, "_DEFAULT_REPORT_DIR", tmp_path / "data" / "reports")
    monkeypatch.setattr(persistence, "_engine", None)
    monkeypatch.setenv("THOMAS_CAPACITY_LEDGER_ROOT", str(tmp_path / "catalog" / ".thomas" / "evolve" / "agent"))


def test_due_tick_moves_disk_and_capacity_work_off_event_loop(w, monkeypatch):
    async def scenario():
        client = await _client(w)
        try:
            await post(client)
            monkeypatch.setattr(autopilot_hold_tick, "port_of", lambda app: client.port)
            _room(monkeypatch, rows=[{"state": "stopped", "execution_id": "e", "conversation_id": "c"}])
            main_thread = threading.get_ident()
            seen = set()

            def guard(module, name):
                original = getattr(module, name)

                def checked(*args, **kwargs):
                    assert threading.get_ident() != main_thread, f"{name} ran on the event loop"
                    seen.add(name)
                    return original(*args, **kwargs)

                monkeypatch.setattr(module, name, checked)

            for module, names in (
                (self_project_queue, ("read", "change")),
                (self_project_routes, ("read_projects",)),
                (thomas_project, ("_read_live",)),
                (machine_capacity, ("_memory", "admission_refusal")),
                (capacity_ledger, ("rows", "measure", "refusal")),
            ):
                for name in names:
                    guard(module, name)

            async def start(app, **kwargs):
                return {"conversation_id": "started", "execution_id": "run"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            await self_project_queue_tick.tick(client.app, w.catalog)
            for _ in range(100):
                if not self_project_queue_tick._in_flight:
                    break
                await asyncio.sleep(0.01)
            assert seen == {
                "read",
                "change",
                "read_projects",
                "_memory",
                "admission_refusal",
                "rows",
                "measure",
                "refusal",
            }
            assert not (await asyncio.to_thread(self_project_queue.read, w.catalog))["queued"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_successful_start_with_failed_finish_write_is_reconciled(w, monkeypatch):
    async def scenario():
        client = await _client(w)
        try:
            queued = await post(client)
            monkeypatch.setattr(autopilot_hold_tick, "port_of", lambda app: client.port)
            projects = []
            _room(monkeypatch, rows=projects)
            calls = []

            async def start(app, **kwargs):
                calls.append(kwargs)
                projects.append(
                    {
                        "state": "running",
                        "conversation_id": "started",
                        "execution_id": "run",
                        "thomas_project": {"queue_id": queued["id"]},
                    }
                )
                return {"conversation_id": "started", "execution_id": "run"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            write = atomic_json.write_json_atomic
            failed = []

            def fail_once(path, data, *args, **kwargs):
                if data["started"] and not failed:
                    failed.append(True)
                    raise OSError("finish replace refused")
                return write(path, data, *args, **kwargs)

            monkeypatch.setattr(atomic_json, "write_json_atomic", fail_once)
            await self_project_queue_tick.tick(client.app, w.catalog)
            for _ in range(100):
                if not self_project_queue_tick._in_flight:
                    break
                await asyncio.sleep(0.01)
            await self_project_queue_tick.project_listing(client.app)
            await asyncio.wait_for(client.app["self_project_listing_slot"]["task"], 5)
            assert failed and len(calls) == 1
            data = self_project_queue.read(w.catalog)
            if data["queued"]:
                row = data["queued"][0]
                assert row["starting"] and row["tries"] == 0
                await self_project_queue_tick.tick(client.app, w.catalog)
            else:
                # The background park loop may have reconciled the completed start.
                assert data["started"][0]["id"] == queued["id"]
            data = self_project_queue.read(w.catalog)
            assert not data["queued"]
            assert data["started"][0]["id"] == queued["id"]
            assert len(calls) == 1
        finally:
            await client.close()

    asyncio.run(scenario())


def test_cancelling_park_loop_while_queue_tick_waits_ends_shutdown(w, monkeypatch):
    async def scenario():
        waiting = asyncio.Event()

        async def queue_tick(_app):
            waiting.set()
            await asyncio.Event().wait()

        async def hold_tick(*_args, **_kwargs):
            return None

        sleeps = 0

        async def sleep(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps > 1:
                await asyncio.sleep(3600)

        monkeypatch.setattr(autopilot_park, "_sleep", sleep)
        monkeypatch.setattr(autopilot_park, "rebuild", lambda *_args: [])
        monkeypatch.setattr(autopilot_park, "resume_due", hold_tick)
        monkeypatch.setattr(autopilot_hold_tick, "run", hold_tick)
        monkeypatch.setattr(self_project_queue_tick, "tick", queue_tick)
        task = asyncio.create_task(autopilot_park.park_loop({}, catalog_root=w.catalog))
        app = {autopilot_park.APP_AUTOPILOT_PARK_TASK: task}
        shutdown = None
        try:
            await asyncio.wait_for(waiting.wait(), 2)
            shutdown = asyncio.create_task(autopilot_park.stop_park_loop(app))
            await asyncio.wait_for(asyncio.shield(shutdown), 0.5)
            assert task.cancelled()
        finally:
            if not task.done():
                task.cancel()
            if shutdown is not None:
                await shutdown

    asyncio.run(scenario())


def test_overlapping_ticks_start_each_queued_project_only_once(w, monkeypatch):
    async def scenario():
        client = await _client(w)
        try:
            await post(client)
            await post(client, "another task")
            monkeypatch.setattr(autopilot_hold_tick, "port_of", lambda app: client.port)
            _room(monkeypatch)
            selected = threading.Event()
            release = threading.Event()
            original_select = self_project_queue_tick._select
            calls = 0

            def delayed_select(*args):
                nonlocal calls
                row = original_select(*args)
                calls += 1
                if calls == 1:
                    selected.set()
                    assert release.wait(5)
                return row

            monkeypatch.setattr(self_project_queue_tick, "_select", delayed_select)
            started = []
            pending = asyncio.Event()

            async def start(app, **kwargs):
                started.append(kwargs)
                await pending.wait()
                return {"conversation_id": "c", "execution_id": "e"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            first = asyncio.create_task(self_project_queue_tick.tick(client.app, w.catalog))
            assert await asyncio.to_thread(selected.wait, 5)
            second = asyncio.create_task(self_project_queue_tick.tick(client.app, w.catalog))
            await asyncio.sleep(0.1)
            release.set()
            await asyncio.wait_for(asyncio.gather(first, second), 5)
            await asyncio.sleep(0)
            assert len(started) == 2
            assert len({call["meta"]["queue_id"] for call in started}) == 2
            pending.set()
            for _ in range(100):
                if not self_project_queue_tick._in_flight:
                    break
                await asyncio.sleep(0.01)
        finally:
            release.set()
            await client.close()

    asyncio.run(scenario())
