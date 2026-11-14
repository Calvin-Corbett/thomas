"""Checks and second looks run on eight threads of their own, never the server's (spec 2026-10-12 Part 1 item 5).

``asyncio.to_thread`` runs on the loop's default executor, which every request handler shares, and a check waiting
for its turn could hold one of those threads for up to an hour.
"""

from __future__ import annotations

import asyncio
import contextvars
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from aiohttp import web

from thomas.core.config import AppConfig
from thomas.server import app_keys, app_lifecycle, autopilot_hold_tick, green_checkout, precard, thomas_project
from thomas.server.precard import workers
from thomas.server.routes import evolve_agent_autopilot as ap


def test_the_check_threads_are_eight_and_their_own() -> None:
    assert workers.CHECK_THREADS == 8 and workers.EXECUTOR._max_workers == 8
    assert precard.workers is workers


def test_a_call_runs_on_a_check_thread_with_the_callers_context() -> None:
    marker: contextvars.ContextVar[str] = contextvars.ContextVar("marker", default="")

    async def scenario() -> tuple[str, str]:
        marker.set("set before the call")
        return await workers.off_the_loop(lambda: (threading.current_thread().name, marker.get()))

    name, seen = asyncio.run(scenario())

    assert name.startswith("precard-check") and seen == "set before the call"


def test_a_hand_in_is_checked_on_the_check_threads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    names: list[str] = []

    def settle(project_root: Path, catalog_root: Path, cid: str, *, expected_gen: object = None) -> None:
        names.append(threading.current_thread().name)

    monkeypatch.setattr(thomas_project, "settle_if_finished", settle)
    monkeypatch.setattr(thomas_project, "settled_record", lambda *_a: None)
    monkeypatch.setattr(autopilot_hold_tick, "hold_if_unfinished", lambda *_a: None)

    asyncio.run(ap._settle_thomas_project(tmp_path, tmp_path, "fc_20261012T000000_threads", gen=[1]))

    assert names and names[0].startswith("precard-check")


def test_a_single_workers_check_runs_on_the_check_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server.chat_delegation_emitter import _DelegationEmitter

    names: list[str] = []
    monkeypatch.setattr(green_checkout, "find_green", lambda _eid: object())
    monkeypatch.setattr(
        precard, "check_for_hand_in", lambda _eid: names.append(threading.current_thread().name) or "ok"
    )

    assert asyncio.run(_DelegationEmitter._check_before_card("e1")) == "ok"
    assert names[0].startswith("precard-check")


def test_a_hand_in_again_is_checked_on_the_check_threads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server import self_change_status

    names: list[str] = []

    def settle_again(*_a: object) -> tuple[None, str]:
        names.append(threading.current_thread().name)
        return None, "not this time"

    monkeypatch.setattr(self_change_status, "_settle_again", settle_again)

    again = self_change_status._hand_in_again(None, tmp_path, tmp_path, "fc_20261012T000000_again", "s1", fresh=False)
    assert asyncio.run(again) == ("", "not this time")
    assert names and names[0].startswith("precard-check")


def test_a_ratchet_second_look_and_hand_in_run_on_the_check_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server.ratchet import attempt

    names: dict[str, str] = {}

    async def ready(_ctx: object, _att: object) -> tuple[str, str, list[str]]:
        return "", "", ["thomas/core/extra.py"]

    def second_look(_ctx: object, _att: object, _verdict: object) -> str:
        names["second look"] = threading.current_thread().name
        return "a second model read it"

    def settle(_summary: str, _chat: str) -> Path:
        names["hand-in"] = threading.current_thread().name
        return Path("self-e1")

    monkeypatch.setattr(attempt, "_ready", ready)
    monkeypatch.setattr(attempt, "_second_look", second_look)
    monkeypatch.setattr(attempt, "landing_summary", lambda *_a: "ratchet: land it")
    ctx: Any = SimpleNamespace(chat="", ledger=SimpleNamespace(record=lambda **_k: None))
    att: Any = SimpleNamespace(candidate=None, dev_sha="d", green=SimpleNamespace(execution_id="e1"), extra=[])
    verdict: Any = SimpleNamespace(as_dict=dict)

    assert asyncio.run(attempt.settle_attempt(ctx, att, verdict, settle=settle)) == "awaiting_card"
    assert sorted(names) == ["hand-in", "second look"]
    assert all(name.startswith("precard-check") for name in names.values())


def test_held_hand_ins_due_at_one_reset_leave_the_servers_threads_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every held row comes due at one reset and each waits for its second-look turn: on the check threads, so a
    request handler's ``asyncio.to_thread`` still gets a thread at once."""
    release = threading.Event()
    names: list[str] = []

    def settle(project_root: Path, catalog_root: Path, cid: str, *, expected_gen: object = None) -> None:
        names.append(threading.current_thread().name)
        release.wait(30)  # waiting for its second-look turn

    monkeypatch.setattr(thomas_project, "settle_if_finished", settle)
    monkeypatch.setattr(thomas_project, "settled_record", lambda *_a: None)
    monkeypatch.setattr(autopilot_hold_tick, "hold_if_unfinished", lambda *_a: None)

    async def scenario() -> bool:
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=4))  # the server's threads
        due = [
            asyncio.create_task(
                ap._settle_thomas_project(tmp_path, tmp_path, f"fc_20261012T000000_due{n:02d}", gen=[n])
            )
            for n in range(24)
        ]
        try:
            for _ in range(500):  # until the first tries are waiting
                if len(names) >= 4:
                    break
                await asyncio.sleep(0.01)
            try:
                await asyncio.wait_for(asyncio.to_thread(lambda: None), timeout=5.0)
                return True
            except TimeoutError:
                return False
        finally:
            release.set()
            await asyncio.gather(*due)

    assert asyncio.run(scenario()), "a request handler waited for a thread behind the held hand-ins"
    assert len(names) == 24 and all(name.startswith("precard-check") for name in names)


def test_a_restart_waits_for_a_check_still_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """Python's own shutdown waits only for the loop's default threads: a restart that left a check running would run
    the old code beside the reloaded server, on the same green."""
    finished: list[float] = []

    def check() -> None:
        time.sleep(0.5)  # still checking when the restart comes
        finished.append(time.monotonic())

    async def no_background_work() -> None:
        return None

    canvas, sweep = (
        ModuleType("thomas.server.chat_delegation_canvas"),
        ModuleType("thomas.server.stale_execution_sweep"),
    )
    canvas.start_canvas_keepalive = lambda: None
    sweep.run_stale_execution_sweeper = no_background_work
    core = ModuleType("thomas.server.app_core")
    app = web.Application()
    core.create_app = lambda _config: app
    for module in (canvas, sweep, core):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(app_lifecycle, "_log_landing_heartbeat", no_background_work)

    class Runner:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def setup(self) -> None:
            return None

        async def cleanup(self) -> None:
            return None

    class Site:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def start(self) -> None:
            asyncio.ensure_future(workers.off_the_loop(check))
            await asyncio.sleep(0.05)  # the check has started on its thread
            app[app_keys.APP_RESTART_REQUESTED] = True  # what /api/server/restart sets
            app[app_keys.APP_SHUTDOWN_EVENT].set()

    monkeypatch.setattr(web, "AppRunner", Runner)
    monkeypatch.setattr(web, "TCPSite", Site)

    with pytest.raises(app_lifecycle._ServerRestartRequested):
        asyncio.run(app_lifecycle.serve_async(AppConfig(), host="127.0.0.1", port=8977))
    returned = time.monotonic()

    assert finished and finished[0] <= returned, "the server stopped while its check still ran"


def test_the_wait_at_shutdown_ends_at_its_timeout() -> None:
    release = threading.Event()

    async def scenario() -> tuple[bool, float, bool]:
        running = asyncio.ensure_future(workers.off_the_loop(release.wait, 30))
        await asyncio.sleep(0.05)
        began = time.monotonic()
        drained = await workers.drain(timeout_s=0.3)
        waited = time.monotonic() - began
        release.set()
        await running
        return drained, waited, await workers.drain(timeout_s=5)

    drained, waited, after = asyncio.run(scenario())

    assert drained is False and 0.25 <= waited < 5, "a check that never ends never holds a restart past the timeout"
    assert after is True, "nothing left once it ended"


def test_a_restart_lets_the_old_generations_check_threads_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """A restart re-imports every module, so the next generation has threads of its own; the old ones must end."""
    old = ThreadPoolExecutor(max_workers=2, thread_name_prefix="precard-check")
    old.submit(lambda: None).result(5)  # a thread that has worked, now idle
    calls: list[str] = []

    async def generation(*_args: object, **_kwargs: object) -> None:
        calls.append("served")
        if len(calls) == 1:
            raise app_lifecycle._ServerRestartRequested()

    loaded = {"thomas.server.precard.workers": SimpleNamespace(EXECUTOR=old), "thomas.server.other": object()}
    monkeypatch.setattr(app_lifecycle, "_check_single_instance", lambda _config, _host, port: port)
    monkeypatch.setattr(app_lifecycle, "_release_lock", lambda _config: None)
    monkeypatch.setattr(app_lifecycle, "serve_async", generation)
    monkeypatch.setattr(app_lifecycle, "sys", SimpleNamespace(modules=loaded))  # the re-import's view, not the real one
    monkeypatch.setattr(app_lifecycle, "shutil", SimpleNamespace(rmtree=lambda *_a, **_k: None))

    app_lifecycle.serve(AppConfig(), host="127.0.0.1", port=8977)

    assert calls == ["served", "served"] and not loaded, "it restarted once, re-importing every module"
    with pytest.raises(RuntimeError):
        old.submit(lambda: None)  # shut down
    for thread in list(old._threads):
        thread.join(5)
        assert not thread.is_alive(), "an idle check thread of the old generation stayed"
