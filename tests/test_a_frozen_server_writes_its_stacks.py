"""A server whose event loop stops running writes every thread's stack, once per freeze.

On 2026-10-23 the caged server froze four times. Its lag watcher logs a stall only
when the loop runs again, so the freezes that never ended logged nothing, and with
no stack tool on the machine each one was found by elimination over hours. The
freeze watch (:func:`thomas.core.event_loop_lag.start_freeze_watch`) runs on a
thread of its own and writes the stacks while the loop is still stuck.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from thomas.core import event_loop_lag
from thomas.core.event_loop_lag import EventLoopLag, start_freeze_watch, watch_event_loop


def _the_call_that_holds_the_loop(seconds: float) -> None:
    time.sleep(seconds)  # a synchronous call on the loop's only thread


def _dumps(folder: Path) -> list[Path]:
    return sorted(folder.glob("loop-freeze-*.txt"))


async def _watched(monitor: EventLoopLag, body) -> None:
    watcher = asyncio.create_task(watch_event_loop(interval_s=0.02, monitor=monitor))
    await asyncio.sleep(0.1)
    try:
        await body()
    finally:
        watcher.cancel()
        with pytest.raises(asyncio.CancelledError):
            await watcher


@pytest.fixture
def log_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_LOG_FILE", str(tmp_path / "thomas.log"))
    return tmp_path


def test_a_frozen_loop_writes_one_dump_that_names_the_blocking_call(log_folder: Path) -> None:
    monitor = EventLoopLag()
    stop = start_freeze_watch(monitor, stall_s=0.3, check_s=0.05)

    async def freeze() -> None:
        _the_call_that_holds_the_loop(1.2)  # four times the threshold: one freeze, one dump
        await asyncio.sleep(0.2)

    try:
        asyncio.run(_watched(monitor, freeze))
    finally:
        stop.set()

    dumps = _dumps(log_folder)
    assert len(dumps) == 1
    text = dumps[0].read_text(encoding="utf-8")
    assert "has not run for" in text
    assert "_the_call_that_holds_the_loop" in text


def test_the_main_thread_is_written_even_beside_more_than_a_hundred_threads(log_folder: Path) -> None:
    # faulthandler stops at 100 threads, newest first; the loop's (main) thread is the oldest.
    release = threading.Event()
    crowd = [threading.Thread(target=release.wait, daemon=True) for _ in range(110)]
    for thread in crowd:
        thread.start()
    monitor = EventLoopLag()
    stop = start_freeze_watch(monitor, stall_s=0.3, check_s=0.05)

    async def freeze() -> None:
        _the_call_that_holds_the_loop(1.2)
        await asyncio.sleep(0.2)

    try:
        asyncio.run(_watched(monitor, freeze))
    finally:
        stop.set()
        release.set()

    text = _dumps(log_folder)[0].read_text(encoding="utf-8")
    main_part = text.split("All threads")[0]
    assert "Main thread" in main_part
    assert "_the_call_that_holds_the_loop" in main_part


def test_a_loop_that_keeps_running_writes_nothing(log_folder: Path) -> None:
    monitor = EventLoopLag()
    stop = start_freeze_watch(monitor, stall_s=0.3, check_s=0.05)

    async def busy_but_fair() -> None:
        for _ in range(8):
            _the_call_that_holds_the_loop(0.1)  # stalls well under the threshold
            await asyncio.sleep(0.02)

    try:
        asyncio.run(_watched(monitor, busy_but_fair))
    finally:
        stop.set()

    assert _dumps(log_folder) == []


def test_a_stopped_watcher_is_not_a_frozen_loop(log_folder: Path) -> None:
    monitor = EventLoopLag()

    async def nothing() -> None:
        return None

    asyncio.run(_watched(monitor, nothing))
    assert monitor.since_wake() == 0.0

    stop = start_freeze_watch(monitor, stall_s=0.1, check_s=0.02)
    try:
        time.sleep(0.4)
    finally:
        stop.set()
    assert _dumps(log_folder) == []


def test_the_dump_goes_beside_the_servers_log(log_folder: Path) -> None:
    path = event_loop_lag.freeze_dump_path(0.0)
    assert path.parent == log_folder
    assert path.name.startswith("loop-freeze-") and path.suffix == ".txt"
