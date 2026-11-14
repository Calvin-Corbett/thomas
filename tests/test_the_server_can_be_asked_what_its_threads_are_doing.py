"""The server can be asked what its threads are doing, from this computer, without an elevated tool.

Thomas's server runs under its own Windows account. On 2026-11-10 it used one to two whole processors while Builds
ran and about a twentieth of the PC while paused, and nothing outside it could look in. You said: "You need to build
a maintenance tunnel into Thomas's cage. This is getting annoying that you don't know what's" going on.

/api/inspect/profile looks at every thread many times a second for a few seconds and lists where the busy ones were;
a thread parked in a wait is left out. /api/inspect/stacks is one look at every thread in full.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core import thread_sampler
from thomas.server.routes.cage_inspector_routes import register_cage_inspector_routes


def spin_for_the_profile(stop: threading.Event) -> None:
    while not stop.is_set():
        sum(range(2000))


@pytest.fixture
def two_threads():
    stop = threading.Event()
    busy = threading.Thread(target=spin_for_the_profile, args=(stop,), name="busy-one", daemon=True)
    parked = threading.Thread(target=stop.wait, name="parked-one", daemon=True)
    busy.start()
    parked.start()
    try:
        yield
    finally:
        stop.set()
        busy.join(5)
        parked.join(5)


def test_a_busy_thread_is_listed_and_a_parked_one_is_not(two_threads) -> None:
    answer = thread_sampler.profile(0.5, interval_s=0.005)

    rows = [row for row in answer["busy"] if "spin_for_the_profile" in row["innermost"]]
    assert rows, answer["busy"]
    assert rows[0]["on"] == "a thread" and rows[0]["percent_of_one_processor"] > 50
    assert answer["waiting_looks"] > 0 and answer["looks"] > 10
    assert not any(row["innermost"] == "threading.py:wait" for row in answer["busy"])


def test_the_load_meter_sleep_is_waiting_not_a_busy_processor() -> None:
    from thomas.core.machine_load import _Sampler

    meter = threading.Thread(target=_Sampler()._read, args=(1.0,), name="test-load-meter")
    meter.start()
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            frame = sys._current_frames().get(meter.ident)
            if frame and frame.f_globals.get("__name__") == "psutil" and frame.f_code.co_name == "cpu_percent":
                break
            time.sleep(0.001)
        else:
            pytest.fail("the load meter never entered its measurement wait")
        stacks = {row["thread"]: row for row in thread_sampler.stacks()["stacks"]}
        assert stacks["test-load-meter"]["waiting"] is True
        answer = thread_sampler.profile(0.1, interval_s=0.005)
        assert not any(row["innermost"] == "__init__.py:cpu_percent" for row in answer["busy"])
        assert answer["waiting_looks"] > 0
    finally:
        meter.join(3)
    assert not meter.is_alive()


@pytest.mark.parametrize("interval", [None, 0])
def test_a_nonblocking_cpu_read_is_not_waiting(monkeypatch: pytest.MonkeyPatch, interval) -> None:
    import psutil

    real = psutil.cpu_times
    observed = []

    def times(*args, **kwargs):
        observed.append(thread_sampler._waiting(sys._getframe(1)))
        return real(*args, **kwargs)

    monkeypatch.setattr(psutil, "cpu_times", times)
    psutil.cpu_percent(interval=interval)
    assert observed and not any(observed)


@pytest.mark.parametrize("method", ["_communicate", "_wait", "_readerthread"])
def test_subprocess_bookkeeping_is_not_a_wait(method: str) -> None:
    import subprocess

    observed = []
    function = getattr(subprocess.Popen, method, None)
    if function is None:
        pytest.skip(f"{method} is not used on this platform")
    code = function.__code__

    def trace(frame, event, arg):
        if frame.f_code is code and event == "line":
            observed.append(thread_sampler._waiting(frame))
            raise RuntimeError("stop before touching process handles")
        return trace

    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        with pytest.raises(RuntimeError, match="stop before touching"):
            function(*([None] * code.co_argcount))
    finally:
        sys.settrace(previous)
    assert observed == [False]


def test_the_thread_that_asks_is_not_in_its_own_answer(two_threads) -> None:
    answer = thread_sampler.profile(0.2, interval_s=0.005)
    assert not any("thread_sampler.py" in row["innermost"] for row in answer["busy"])


def test_a_profile_is_never_longer_than_its_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(thread_sampler, "MAX_SECONDS", 0.2)
    began = time.perf_counter()
    answer = thread_sampler.profile(9999)
    assert time.perf_counter() - began < 2 and answer["seconds"] == 0.2


def test_one_look_gives_every_thread_whole_and_says_which_are_parked(two_threads) -> None:
    answer = thread_sampler.stacks()

    by_name = {row["thread"]: row for row in answer["stacks"]}
    assert by_name["parked-one"]["waiting"] is True
    assert by_name["busy-one"]["waiting"] is False
    assert any("spin_for_the_profile" in line for line in by_name["busy-one"]["stack"])


@pytest.mark.asyncio
async def test_both_are_answered_only_on_this_computer(tmp_path: Path) -> None:
    app = web.Application()
    register_cage_inspector_routes(app, agent_dir=lambda: tmp_path, green_root=lambda: tmp_path)

    async with TestClient(TestServer(app)) as client:
        profile = await (await client.get("/api/inspect/profile?seconds=0.2")).json()
        stacks = await (await client.get("/api/inspect/stacks")).json()
        from_elsewhere = await client.get("/api/inspect/profile", headers={"X-Forwarded-For": "203.0.113.9"})

    assert profile["ok"] is True and profile["looks"] > 0 and isinstance(profile["busy"], list)
    assert stacks["ok"] is True and stacks["threads"] >= 1
    assert from_elsewhere.status == 403
