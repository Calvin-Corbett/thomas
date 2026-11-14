"""Shared helpers for the tests of a check still waiting for its turn when Thomas begins to stop.

Used by tests/test_a_check_waiting_at_a_restart_leaves_without_a_strike.py,
tests/test_a_self_fix_whose_check_waited_at_a_restart_is_not_handed_in.py and
tests/test_a_server_generation_owns_its_startup_and_retries.py. The reservation ledger is a temporary folder with room
for every check, and the server is the real ``serve_async`` around a runner and a site that bind nothing: its stop runs
in its real order, with no port, no background sweep, no git work and no network service.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from aiohttp import web

from thomas.core.config import AppConfig
from thomas.server import app_keys, app_lifecycle, capacity_ledger, green_checkout
from thomas.server.precard import check, workers

Hook = Callable[[web.Application], Awaitable[None]]


def in_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, wait_s: float = 30) -> green_checkout.Green:
    """A ledger in *tmp_path* with room for any check, whose wait for a turn gives up after *wait_s*; the green."""
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(capacity_ledger, "measure", lambda _path: capacity_ledger.Room(30 * 1024**3, None, None))
    monkeypatch.setattr(check, "ADMISSION_WAIT_S", wait_s)
    monkeypatch.setattr(check.proofs, "select", lambda *_a, **_k: SimpleNamespace(files=["example.py"]))
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path)
    monkeypatch.setattr(check.green_handoff, "dev_tip", lambda _eid: "dev")
    return green_checkout.Green("same", tmp_path, tmp_path, "base", tmp_path)


def admitted(green: green_checkout.Green) -> check.Checked:
    """The real wait for a turn and the check after it (``check._admitted``), as the parallel check calls it."""
    return check._admitted(green, "dev", "patch", ["example.py"], sys.executable)


@contextmanager
def one_ahead(tmp_path: Path) -> Iterator[None]:
    """Another check of the same green holds its turn: a check of it started now waits in line behind that one."""
    with capacity_ledger.admitted(
        "check:same", kind="check", disk_bytes=check.CHECK_DISK_BYTES, where=tmp_path, root=capacity_ledger.folder()
    ):
        yield


def until_waiting(seconds: float = 5) -> bool:
    """Whether, within *seconds*, a check has taken its place in line behind the one ahead."""
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if sorted(str(row.get("state")) for row in capacity_ledger.rows()) == ["admitted", "waiting"]:
            return True
        time.sleep(0.01)
    return False


def until_idle(seconds: float = 15) -> bool:
    """Whether every call on the check threads has ended within *seconds* (an old server's check may outlive it)."""
    until = time.monotonic() + seconds
    while workers._in_flight and time.monotonic() < until:
        time.sleep(0.05)
    return not workers._in_flight


async def _nothing(*_args: object) -> None:
    return None


def serve_once(
    monkeypatch: pytest.MonkeyPatch,
    started: Hook = _nothing,
    *,
    setup: Hook = _nothing,
    restart: bool = True,
    drain_s: float | None = None,
    stopped: Hook | None = None,
) -> web.Application:
    """The real ``serve_async``, once: *setup* runs as its runner is set up and *started* once its site is up; then
    the server stops, for a restart when *restart*, else for a shutdown.

    *drain_s* shortens the stop's wait for the check threads (300 s in a real server); *stopped* runs inside the stop,
    right after that wait, while the event loop is still running.
    """
    app = web.Application()
    core = ModuleType("thomas.server.app_core")
    core.create_app = lambda _config: app
    canvas = ModuleType("thomas.server.chat_delegation_canvas")
    canvas.start_canvas_keepalive = lambda: None
    sweep = ModuleType("thomas.server.stale_execution_sweep")
    sweep.run_stale_execution_sweeper = _nothing
    for module in (core, canvas, sweep):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(app_lifecycle, "_log_landing_heartbeat", _nothing)
    real_drain = workers.drain

    async def drain(timeout_s: float = workers.DRAIN_S) -> bool:
        drained = await real_drain(timeout_s if drain_s is None else drain_s)
        if stopped is not None:
            await stopped(app)
        return drained

    monkeypatch.setattr(workers, "drain", drain)

    class Runner:
        addresses = [("127.0.0.1", 1234)]

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def setup(self) -> None:
            await setup(app)

        async def cleanup(self) -> None:
            return None

    class Site:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def start(self) -> None:
            await started(app)
            app[app_keys.APP_RESTART_REQUESTED] = restart  # what /api/server/restart sets
            app[app_keys.APP_SHUTDOWN_EVENT].set()

    monkeypatch.setattr(web, "AppRunner", Runner)
    monkeypatch.setattr(web, "TCPSite", Site)
    with pytest.raises(app_lifecycle._ServerRestartRequested) if restart else contextlib.nullcontext():
        asyncio.run(app_lifecycle.serve_async(AppConfig(), host="127.0.0.1", port=0))
    return app
