"""Queued self-projects survive restarts and start only when room is available."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests.test_a_thomas_project_starts_without_chat import ASK, CLAUDE
from tests.test_project_queue_cached_capacity import w as cached_w  # noqa: F401 -- shared fixture
from thomas.core import atomic_json, machine_capacity, persistence
from thomas.server import (
    autopilot_hold_tick,
    capacity_ledger,
    capacity_ledger_locks,
    self_project_queue,
    self_project_queue_tick,
    thomas_project,
)
from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN
from thomas.server.routes import self_project_queue_routes, self_project_routes

URL = "/api/self/projects/queue"


@pytest.fixture
def w(cached_w, tmp_path, monkeypatch):
    from thomas.forge.anvil import forge_code_projects
    from thomas.server import green_checkout, green_handoff, self_change_status

    cached_w.tmp = tmp_path
    cached_w.blue = tmp_path / "blue"
    cached_w.greens = tmp_path / "greens"
    cached_w.board = tmp_path / "board"
    cached_w.starts = []
    for folder in (cached_w.greens / "work", cached_w.greens / "git", cached_w.board):
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(cached_w.greens))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(cached_w.board))
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: cached_w.blue)
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setattr(green_handoff, "_end_processes", lambda green: None)
    monkeypatch.setattr(self_change_status, "outbox_dir", lambda: tmp_path / "outbox")

    async def hook(body, *, port):
        cached_w.starts.append({**body, "port": port})
        return 200, {"ok": True, "conversation_id": body["conversation_id"], "run_id": "run"}

    cached_w.hook = hook
    return cached_w


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, w) -> None:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    # Persistence computes its default at import time; an app in this test can
    # otherwise initialize its singleton against the real profile's state file.
    monkeypatch.setattr(persistence, "_DEFAULT_STATE_FILE", tmp_path / "data" / "thomas_state.json")
    monkeypatch.setattr(persistence, "_DEFAULT_REPORT_DIR", tmp_path / "data" / "reports")
    monkeypatch.setattr(persistence, "_engine", None)
    monkeypatch.setenv("THOMAS_CAPACITY_LEDGER_ROOT", str(tmp_path / "catalog" / ".thomas" / "evolve" / "agent"))
    monkeypatch.setattr(autopilot_hold_tick, "port_of", lambda app: int(app.get("queue_test_port", 0)))


async def _client(w, *, remote="127.0.0.1"):
    app = web.Application()
    app[self_project_routes.APP_PRAXIS_START_CODE_RUN] = w.hook

    def require_loopback(request):
        if remote not in {"127.0.0.1", "::1"}:
            raise web.HTTPForbidden()

    self_project_routes.register_self_project_routes(app, require_loopback=require_loopback)
    self_project_queue_routes.register_self_project_queue_routes(app, require_loopback=require_loopback)
    client = TestClient(TestServer(app, host="127.0.0.1"))
    await client.start_server()
    return client


async def _warm_listing(app):
    await self_project_queue_tick.project_listing(app)
    await asyncio.wait_for(asyncio.shield(app["self_project_listing_slot"]["task"]), 5)
    assert self_project_queue_tick._cached_listing(app) is not None


async def post(client, ask=ASK):
    response = await client.post(URL, json={"request": ask, "settings": CLAUDE})
    assert response.status == 200, await response.text()
    return await response.json()


def test_routes_persist_order_and_refusals(w):
    async def scenario():
        client = await _client(w)
        try:
            first, second = await post(client), await post(client, "Second task")
            assert (first["place"], second["place"]) == (1, 2)
            listed = await (await client.get(URL)).json()
            assert [row["id"] for row in listed["queued"]] == [first["id"], second["id"]]
            assert listed["queued"][0]["request"] == ASK
            assert listed["queued"][0]["settings"] == CLAUDE
            assert listed["queued"][0]["tries"] == 0
            assert listed["capacity"]["running"] == 0
            assert listed["capacity"]["starting"] == 0
            assert "blocked_by" in listed["capacity"]
            direct, queued = await client.post("/api/self/projects", json={}), await client.post(URL, json={})
            assert (direct.status, await direct.json()) == (queued.status, await queued.json())
            assert len((await (await client.get(URL)).json())["queued"]) == 2
            importlib.reload(self_project_queue)
            assert [row["id"] for row in self_project_queue.read(w.catalog)["queued"]] == [first["id"], second["id"]]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_bad_file_remote_and_atomic_replace(w, monkeypatch):
    async def scenario():
        client = await _client(w)
        try:
            await post(client)
            path = self_project_queue.path(w.catalog)
            before = path.read_bytes()

            def fail(*args):
                raise OSError("replace refused")

            original_replace = atomic_json.os.replace
            monkeypatch.setattr(atomic_json.os, "replace", fail)
            with pytest.raises(OSError):
                self_project_queue.enqueue(w.catalog, ASK, CLAUDE, "", client.port)
            assert path.read_bytes() == before
            assert not list(path.parent.glob(f".{path.name}.*"))
            monkeypatch.setattr(atomic_json.os, "replace", original_replace)
            path.write_text("not JSON", encoding="utf-8")
            for response in (await client.get(URL), await client.post(URL, json={"request": ASK, "settings": CLAUDE})):
                assert response.status == 409 and "could not be read" in (await response.json())["error"]
            assert path.read_bytes() == b"not JSON"
            path.write_bytes(before)
        finally:
            await client.close()
        remote = await _client(w, remote="198.51.100.4")
        try:
            queued_before = self_project_queue.read(w.catalog)["queued"]
            assert (await remote.get(URL)).status == 403
            assert (await remote.post(URL, json={"request": ASK, "settings": CLAUDE})).status == 403
            assert self_project_queue.read(w.catalog)["queued"] == queued_before
        finally:
            await remote.close()

    asyncio.run(scenario())


def _room(monkeypatch, *, rows=None, unreadable=None, machine=None, ledger=None):
    monkeypatch.setattr(machine_capacity, "_memory", lambda: (16 * 1024**3, 8 * 1024**3))
    monkeypatch.setattr(
        self_project_routes, "read_projects", lambda *a, **kw: {"projects": rows or [], "unreadable": unreadable or []}
    )
    monkeypatch.setattr(machine_capacity, "admission_refusal", lambda active: machine)
    monkeypatch.setattr(capacity_ledger, "refusal", lambda *a, **kw: ledger)
    monkeypatch.setattr(capacity_ledger, "rows", lambda: [])
    monkeypatch.setattr(capacity_ledger, "measure", lambda root: capacity_ledger.Room(100 * 1024**3, None, None))


def test_queue_reports_running_count_and_capacity_blocker(w, monkeypatch):
    async def scenario():
        monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
        client = await _client(w)
        try:
            monkeypatch.setattr(
                self_project_routes,
                "read_projects",
                lambda *a, **kw: {
                    "projects": [{"state": "running"}] * 5 + [{"state": "waiting"}],
                    "unreadable": [],
                },
            )
            monkeypatch.setattr(self_project_routes, "running_projects", lambda _app: {f"run-{i}" for i in range(5)})
            monkeypatch.setattr(machine_capacity, "_memory", lambda: (16 * 1024**3, 8 * 1024**3))
            monkeypatch.setattr(machine_capacity, "admission_refusal", lambda active: f"Model limit at {active} runs")
            queued = await post(client)
            self_project_queue.change(
                w.catalog,
                lambda data: data["queued"][0].update({"starting": {"pid": 1, "at": 1}}),
            )
            response = await (await client.get(URL)).json()
            assert response["queued"][0]["id"] == queued["id"]
            assert response["capacity"] == {"running": 5, "starting": 1, "blocked_by": "Model limit at 6 runs"}
            monkeypatch.setattr(
                self_project_routes, "read_projects", lambda *a, **kw: {"projects": [], "unreadable": ["broken"]}
            )
            slot = client.app["self_project_listing_slot"]
            slot["snapshot"] = {"projects": [], "unreadable": ["broken"]}
            assert "could not all be read" in (await (await client.get(URL)).json())["capacity"]["blocked_by"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_tick_fills_available_slots_without_waiting_for_another_tick(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        try:
            _room(monkeypatch)
            pending = asyncio.Event()
            started = []

            async def start(app, **kwargs):
                started.append(kwargs)
                await pending.wait()
                return {"conversation_id": "c1", "execution_id": "e1"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            first = await post(client)
            await post(client, "second")
            await post(client, "third")
            await post(client, "fourth")
            await post(client, "fifth")
            await post(client, "sixth")
            client.app["queue_test_port"] = client.port
            await self_project_queue_tick.tick(client.app, w.catalog)
            await asyncio.sleep(0)
            await self_project_queue_tick.tick(client.app, w.catalog)
            assert [row["request"] for row in started] == [
                "Make the Send button blue",
                "second",
                "third",
                "fourth",
                "fifth",
                "sixth",
            ]
            assert started[0]["meta"]["queue_id"] == first["id"]
            assert started[0]["meta"]["queued_at"] == first["queued_at"]
            assert (await (await client.get(URL)).json())["capacity"]["starting"] == 6
            start_tasks = tuple(self_project_queue_tick._start_tasks)
            pending.set()
            await asyncio.wait_for(asyncio.gather(*start_tasks), timeout=10)
            deadline = asyncio.get_running_loop().time() + 5
            while (
                len(self_project_queue.read(w.catalog)["started"]) < 6 and asyncio.get_running_loop().time() < deadline
            ):
                await asyncio.sleep(0.02)
            assert len(self_project_queue.read(w.catalog)["started"]) == 6
            await self_project_queue_tick.tick(client.app, w.catalog)
            assert len(started) == 6
        finally:
            await client.close()

    asyncio.run(scenario())


def test_selection_never_reads_capacity_ledger_while_queue_lock_is_held(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    _room(monkeypatch)
    queued = self_project_queue.enqueue(w.catalog, ASK, CLAUDE, "session", 8899)
    reads = []
    real_rows = capacity_ledger.rows
    queue_lock = capacity_ledger_locks._lock

    def rows():
        # Detect a nested ledger read before invoking the actual read, which
        # would wait forever on the same thread's non-reentrant lock.
        assert not queue_lock.locked(), "ledger read inside queue change deadlocks"
        reads.append(True)
        return real_rows()

    monkeypatch.setattr(capacity_ledger, "rows", rows)
    selected = self_project_queue_tick._select(w.catalog, {}, 8899, self_project_queue_tick.time.time())
    assert selected is not None and selected["id"] == queued["id"]
    assert reads


def test_selection_aborts_if_another_start_was_marked_after_capacity_check(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    _room(monkeypatch)
    first = self_project_queue.enqueue(w.catalog, ASK, CLAUDE, "session", 8899)
    second = self_project_queue.enqueue(w.catalog, "another project", CLAUDE, "session", 8899)
    blocker = self_project_queue_tick.capacity_blocker

    def concurrent_start(active, now):
        result = blocker(active, now)
        self_project_queue.change(
            w.catalog,
            lambda data: next(row for row in data["queued"] if row["id"] == second["id"]).update(
                starting={"pid": -1, "at": now}
            ),
        )
        return result

    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", concurrent_start)
    assert self_project_queue_tick._select(w.catalog, {}, 8899, self_project_queue_tick.time.time()) is None
    rows = self_project_queue.read(w.catalog)["queued"]
    assert not next(row for row in rows if row["id"] == first["id"]).get("starting")
    assert next(row for row in rows if row["id"] == second["id"])["starting"]


def test_selection_blocks_when_capacity_ledger_refuses(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    _room(monkeypatch)
    self_project_queue.enqueue(w.catalog, ASK, CLAUDE, "session", 8899)
    monkeypatch.setattr(capacity_ledger, "refusal", lambda *args, **kwargs: "capacity full")
    assert self_project_queue_tick._select(w.catalog, {}, 8899, self_project_queue_tick.time.time()) is None
    assert not self_project_queue.read(w.catalog)["queued"][0].get("starting")


def test_reload_drain_preserves_queued_start_without_spending_a_try(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        try:
            _room(monkeypatch)
            queued = await post(client)
            calls = []

            async def start(*_args, **_kwargs):
                calls.append(True)
                raise AssertionError("no green should be cloned while draining")

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            client.app[APP_LANDED_CODE_DRAIN] = True
            for _ in range(self_project_queue_tick.MAX_START_TRIES + 1):
                await self_project_queue_tick.tick(client.app, w.catalog)
            row = self_project_queue.read(w.catalog)["queued"][0]
            assert row["id"] == queued["id"] and row["tries"] == 0
            assert not row.get("starting") and not calls

            # A queued selection already booked before the drain must also go back without a penalty.
            client.app.pop(APP_LANDED_CODE_DRAIN)
            await _warm_listing(client.app)
            selected = await asyncio.to_thread(
                self_project_queue_tick._select, w.catalog, client.app, client.port, self_project_queue_tick.time.time()
            )
            assert selected is not None and selected["starting"]
            client.app[APP_LANDED_CODE_DRAIN] = True
            await self_project_queue_tick._start(client.app, w.catalog, selected, client.port)
            row = self_project_queue.read(w.catalog)["queued"][0]
            assert row["tries"] == 0 and not row.get("starting") and not calls
        finally:
            await client.close()

    asyncio.run(scenario())


def test_desktop_queued_project_starts_from_caged_worker(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        desktop, caged = await _client(w), await _client(w)
        try:
            _room(monkeypatch)
            queued = await post(desktop)
            assert self_project_queue.read(w.catalog)["queued"][0]["port"] == desktop.port
            assert desktop.port != caged.port
            starts = []

            async def start(app, **kwargs):
                starts.append((app, kwargs))
                return {"conversation_id": "desktop-c", "execution_id": "desktop-e"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            monkeypatch.setattr(self_project_queue_tick.autopilot_hold_tick, "port_of", lambda app: caged.port)
            await self_project_queue_tick.tick(caged.app, w.catalog)
            await asyncio.sleep(0.05)
            assert len(starts) == 1
            assert starts[0][0] is caged.app
            assert starts[0][1]["meta"]["queue_id"] == queued["id"]
            assert starts[0][1]["port"] == caged.port
            for _ in range(100):
                if self_project_queue.read(w.catalog)["started"]:
                    break
                await asyncio.sleep(0.02)
            assert self_project_queue.read(w.catalog)["started"][0]["id"] == queued["id"]
        finally:
            await desktop.close()
            await caged.close()

    asyncio.run(scenario())


def test_desktop_park_tick_cannot_plan_or_start(monkeypatch):
    from thomas.server import self_improvement_planner

    monkeypatch.delenv("THOMAS_OWNER_DESK", raising=False)
    monkeypatch.setattr(self_project_queue_tick.autopilot_hold_tick, "port_of", lambda app: 8899)
    monkeypatch.setattr(self_project_queue_tick.thomas_project, "_catalog_root", lambda: Path("."))
    monkeypatch.setattr(
        self_improvement_planner,
        "scan",
        lambda *args: pytest.fail("desktop must not plan projects"),
    )
    monkeypatch.setattr(
        self_project_queue_tick,
        "_select",
        lambda *args: pytest.fail("desktop must not claim projects"),
    )
    asyncio.run(self_project_queue_tick.tick({self_project_queue_tick.APP_PRAXIS_START_CODE_RUN: object()}, Path(".")))


def test_queue_waits_when_other_code_runs_fill_build_slots(w, monkeypatch):
    from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS

    async def scenario():
        monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
        client = await _client(w)
        try:
            _room(monkeypatch, rows=[{"state": "running"}] * 4)
            monkeypatch.setattr(
                machine_capacity,
                "admission_refusal",
                lambda active: "All 8 runs are busy" if active >= 8 else None,
            )
            # Populate the test's live registry in place.
            runs = client.app._state.setdefault(APP_EVOLVE_AGENT_RUNS, {})
            runs.update(
                {
                    f"project-{i}" if i < 4 else f"code-{i}": {
                        "session": {"proc": type("Proc", (), {"returncode": None})()}
                    }
                    for i in range(8)
                }
            )
            queued = await post(client)
            starts = []

            async def start(*_args, **_kwargs):
                starts.append(True)
                raise AssertionError("Build is full: no project should start")

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            await self_project_queue_tick.project_listing(client.app)
            status = self_project_queue_tick.queue_status(client.app, self_project_queue.read(w.catalog))
            assert status["running"] == 8
            assert status["blocked_by"] == "All 8 runs are busy"
            for _ in range(self_project_queue_tick.MAX_START_TRIES + 1):
                await self_project_queue_tick.tick(client.app, w.catalog)
            row = self_project_queue.read(w.catalog)["queued"][0]
            assert row["id"] == queued["id"] and row["tries"] == 0
            assert not row.get("starting") and not starts
        finally:
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "states,unreadable,machine,ledger,expected",
    [
        (["running", "repair round 1", "paused", "running"], None, None, None, True),
        (["running", "repair round 1", "paused", "stopped", "handed in"], None, None, None, True),
        ([], ["unreadable green"], None, None, False),
        ([], None, "no memory", None, False),
        ([], None, None, "no disk", False),
        ([], None, None, None, False),
    ],
)
def test_tick_capacity(w, monkeypatch, states, unreadable, machine, ledger, expected):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        try:
            await post(client)
            client.app["queue_test_port"] = client.port
            _room(
                monkeypatch,
                rows=[{"state": state} for state in states],
                unreadable=unreadable,
                machine=machine,
                ledger=ledger,
            )
            if not states and not unreadable and not machine and not ledger:
                monkeypatch.setattr(machine_capacity, "_memory", lambda: (None, None))
            calls = []

            async def start(app, **kw):
                calls.append(kw)
                return {"conversation_id": "c", "execution_id": "e"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            await self_project_queue_tick.tick(client.app, w.catalog)
            await asyncio.sleep(0.05)
            assert bool(calls) == expected
            if not expected:
                assert self_project_queue.read(w.catalog)["queued"][0]["tries"] == 0
        finally:
            await client.close()

    asyncio.run(scenario())


def test_selection_setup_waits_for_listing_after_bounded_read_returns(w, monkeypatch):
    import threading

    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    release = threading.Event()

    async def scenario():
        client = await _client(w)
        warming = None
        try:
            _room(monkeypatch)
            await post(client)
            reader = self_project_routes.read_projects
            returned = asyncio.Event()
            project_listing = self_project_queue_tick.project_listing

            def slow_reader(*args, **kwargs):
                assert release.wait(5)
                return reader(*args, **kwargs)

            async def bounded_listing(app):
                listing = await project_listing(app)
                returned.set()
                return listing

            monkeypatch.setattr(self_project_routes, "read_projects", slow_reader)
            monkeypatch.setattr(self_project_queue_tick, "project_listing", bounded_listing)
            warming = asyncio.create_task(_warm_listing(client.app))
            await asyncio.wait_for(returned.wait(), 5)
            assert not warming.done()
            release.set()
            await warming
            selected = await asyncio.to_thread(
                self_project_queue_tick._select, w.catalog, client.app, client.port, self_project_queue_tick.time.time()
            )
            assert selected is not None
        finally:
            release.set()
            if warming is not None:
                await asyncio.gather(warming, return_exceptions=True)
            await client.close()

    asyncio.run(scenario())


def test_selection_never_reads_capacity_ledger_while_queue_lock_is_held(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        try:
            _room(monkeypatch)
            await post(client)
            await _warm_listing(client.app)
            original_change = self_project_queue.change
            inside_lock = False
            checked = []
            original_blocker = self_project_queue_tick.capacity_blocker

            def blocker(*args, **kwargs):
                assert not inside_lock, "capacity ledger read under queue lock"
                checked.append(True)
                return original_blocker(*args, **kwargs)

            def change(catalog, callback):
                def guarded(data):
                    nonlocal inside_lock
                    inside_lock = True
                    try:
                        return callback(data)
                    finally:
                        inside_lock = False

                return original_change(catalog, guarded)

            monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", blocker)
            monkeypatch.setattr(self_project_queue, "change", change)
            selected = await asyncio.to_thread(
                self_project_queue_tick._select, w.catalog, client.app, client.port, self_project_queue_tick.time.time()
            )
            assert selected is not None and checked
        finally:
            await client.close()

    asyncio.run(scenario())


def test_selection_aborts_if_another_start_was_marked_after_capacity_check(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        try:
            _room(monkeypatch)
            first = await post(client)
            second = await post(client, "second")
            await _warm_listing(client.app)
            original_change = self_project_queue.change
            injected = False

            def change(catalog, callback):
                nonlocal injected
                if not injected and callback.__name__ == "mark":
                    injected = True
                    original_change(
                        catalog,
                        lambda data: next(row for row in data["queued"] if row["id"] == second["id"]).update(
                            starting={"pid": -1, "at": self_project_queue_tick.time.time()}
                        ),
                    )
                return original_change(catalog, callback)

            monkeypatch.setattr(self_project_queue, "change", change)
            selected = await asyncio.to_thread(
                self_project_queue_tick._select, w.catalog, client.app, client.port, self_project_queue_tick.time.time()
            )
            assert injected and selected is None
            assert not next(
                row for row in self_project_queue.read(w.catalog)["queued"] if row["id"] == first["id"]
            ).get("starting")
        finally:
            await client.close()

    asyncio.run(scenario())


def test_selection_blocks_when_capacity_ledger_refuses(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        try:
            _room(monkeypatch, ledger="capacity exhausted")
            queued = await post(client)
            await _warm_listing(client.app)
            checked = []

            def refuse(*args, **kwargs):
                checked.append(True)
                return "capacity exhausted"

            monkeypatch.setattr(capacity_ledger, "refusal", refuse)
            selected = await asyncio.to_thread(
                self_project_queue_tick._select, w.catalog, client.app, client.port, self_project_queue_tick.time.time()
            )
            assert selected is None and checked
            assert not next(
                row for row in self_project_queue.read(w.catalog)["queued"] if row["id"] == queued["id"]
            ).get("starting")
        finally:
            await client.close()

    asyncio.run(scenario())


def test_warm_project_listing_serves_capacity_and_start_without_rescanning(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        try:
            _room(monkeypatch)
            queued = await post(client)
            client.app["queue_test_port"] = client.port
            await _warm_listing(client.app)
            slot = client.app["self_project_listing_slot"]
            slot["served"] = False
            slot["dirty"] = False
            # Keep the warm snapshot inside the cache's freshness window even on slow CI.
            slot["updated"] = self_project_queue_tick.time.monotonic() + 3600

            def no_scan(*_args, **_kwargs):
                raise AssertionError("capacity and starter must use the cached project listing")

            monkeypatch.setattr(self_project_routes, "read_projects", no_scan)

            async def start(*args, **kwargs):
                return {"conversation_id": "cached-start", "execution_id": "run"}

            monkeypatch.setattr(thomas_project, "start_thomas_project", start)
            capacity = (await (await client.get(URL)).json())["capacity"]
            assert capacity["running"] == 0
            assert capacity["blocked_by"] is None
            await self_project_queue_tick.tick(client.app, w.catalog)
            data = self_project_queue.read(w.catalog)
            assert any(row["id"] == queued["id"] and row.get("starting") for row in data["queued"]) or any(
                row["id"] == queued["id"] for row in data["started"]
            )
        finally:
            await client.close()

    asyncio.run(scenario())


def test_retry_give_up(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        try:
            await post(client)
            client.app["queue_test_port"] = client.port
            _room(monkeypatch)
            calls = []

            async def fail(app, **kw):
                calls.append(kw)
                raise thomas_project.ThomasProjectError("Build is busy")

            monkeypatch.setattr(thomas_project, "start_thomas_project", fail)
            clock = [10000.0]
            monkeypatch.setattr(self_project_queue_tick.time, "time", lambda: clock[0])
            await _warm_listing(client.app)
            for n in range(self_project_queue_tick.MAX_START_TRIES):
                await self_project_queue_tick.tick(client.app, w.catalog)
                await asyncio.wait_for(asyncio.gather(*tuple(self_project_queue_tick._start_tasks)), 5)
                row = self_project_queue.read(w.catalog)["queued"][0]
                assert row["tries"] == n + 1 and row["last_reason"] == "Build is busy" and not row.get("starting")
                await self_project_queue_tick.tick(client.app, w.catalog)
                assert len(calls) == n + 1
                clock[0] += self_project_queue_tick.RETRY_AFTER_S
            assert row["given_up"]
            await self_project_queue_tick.tick(client.app, w.catalog)
            assert len(calls) == self_project_queue_tick.MAX_START_TRIES
        finally:
            await client.close()

    asyncio.run(scenario())


def test_real_start_carries_queue_id(w, monkeypatch):
    from tests.test_a_thomas_project_starts_without_chat import _git

    w.blue.mkdir()
    _git(w.blue, "init", "-b", "main")
    _git(w.blue, "config", "user.email", "test@example.invalid")
    _git(w.blue, "config", "user.name", "Test")
    (w.blue / "README.md").write_text("the running copy\n", encoding="utf-8")
    _git(w.blue, "add", "README.md")
    _git(w.blue, "commit", "-m", "base")
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        try:
            queued = await post(client)
            client.app["queue_test_port"] = client.port
            _room(monkeypatch)
            await self_project_queue_tick.tick(client.app, w.catalog)
            for _ in range(100):
                await asyncio.sleep(0.05)
                if self_project_queue.read(w.catalog)["started"]:
                    break
            listed = await (await client.get(URL)).json()
            assert not listed["queued"]
            from thomas.forge.anvil import forge_code_store

            row = listed["started"][0]
            stored = forge_code_store.load_conversation(w.greens / "work" / row["execution_id"], row["conversation_id"])
            assert stored["thomas_project"]["queue_id"] == queued["id"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_interrupted_start(w, monkeypatch):
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")

    async def scenario():
        client = await _client(w)
        try:
            first, second = await post(client), await post(client, "second")
            for item in (first, second):
                self_project_queue.change(
                    w.catalog,
                    lambda data: next(row for row in data["queued"] if row["id"] == item["id"]).update(
                        starting={"pid": -1, "at": 1}
                    ),
                )
            client.app["queue_test_port"] = client.port
            from thomas.forge.anvil import forge_code_store

            work = w.greens / "work" / "e"
            cid = forge_code_store.new_conversation(
                work,
                title="booked",
                thomas_project={"queue_id": first["id"], "conversation_id": "booked", "execution_id": "e"},
            )["id"]
            _room(monkeypatch, rows=[{"state": "running", "conversation_id": cid, "execution_id": "e"}])
            await self_project_queue_tick.tick(client.app, w.catalog)
            data = self_project_queue.read(w.catalog)
            assert data["started"][0]["id"] == first["id"]
            assert data["given_up"][0]["id"] == second["id"]
            assert "server stopped before this project registered" in data["given_up"][0]["reason"]
        finally:
            await client.close()

    asyncio.run(scenario())
