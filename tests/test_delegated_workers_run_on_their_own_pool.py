"""Delegated workers run on a pool of their own, of THOMAS_DELEGATION_MAX_ACTIVE_WORKERS threads (default 16).

Before, they ran on the event loop's shared default pool, where a finishing worker's notification needed a thread
the finishing workers held (see test_many_delegated_workers_finishing_together_all_report.py). Ported from
refs/salvage/praxis-native-20260919/wt-native-scheduling (694a668b), without its admission groups: the worker's
heartbeat plays the salvage's fence. Each test drives ``_start_worker_thread`` and ``_stop_worker`` as the
supervisor does, with stand-in runners.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from thomas.server import chat_delegation_runner_events as events
from thomas.server.chat_delegation_emitter import _DelegationEmitter, worker_heartbeat

LIMIT_ENV = "THOMAS_DELEGATION_MAX_ACTIVE_WORKERS"


def _start(runner: Any, execution_id: str) -> tuple[asyncio.Future, Any]:
    emitter = _DelegationEmitter(lambda _event: asyncio.sleep(0))
    thread, _sink, heartbeat = events._start_worker_thread(runner, None, emitter, {}, execution_id)
    return thread, heartbeat


def _holder(release: threading.Event, ran: list[str], name: str) -> Any:
    async def runner(_app: Any, **_kwargs: Any) -> None:
        ran.append(name)
        while not release.is_set():
            await asyncio.sleep(0.01)

    return runner


def test_the_pool_size_comes_from_the_environment_and_defaults_to_16(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server import chat_delegation_scheduler as scheduler

    monkeypatch.delenv(LIMIT_ENV, raising=False)
    assert scheduler.max_active_workers() == 16
    for raw, expected in (("4", 4), ("1", 1), ("0", 16), ("-3", 16), ("many", 16), ("", 16)):
        monkeypatch.setenv(LIMIT_ENV, raw)
        assert scheduler.max_active_workers() == expected, raw


def test_a_worker_runs_on_the_delegation_pool_never_the_shared_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LIMIT_ENV, "3")
    seen: list[str] = []

    async def runner(_app: Any, **_kwargs: Any) -> None:
        seen.append(threading.current_thread().name)

    async def main() -> tuple[Any, Any]:
        thread, _heartbeat = _start(runner, "exec-own-pool")
        await asyncio.wait_for(thread, timeout=10)
        assert seen and seen[0].startswith("thomas-delegation-worker"), f"the worker ran on the shared pool: {seen}"
        from thomas.server.chat_delegation_scheduler import scheduler_for_running_loop

        return scheduler_for_running_loop(), scheduler_for_running_loop()

    first, again = asyncio.run(main())
    assert first is again and first.limit == 3
    assert first.snapshot()["queued"] == 0 and first.snapshot()["active"] == 0
    assert worker_heartbeat("exec-own-pool") is None, "the worker's thread returned and let its heartbeat go"


def test_a_worker_waiting_for_a_thread_is_not_silent_and_starts_when_one_is_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LIMIT_ENV, "1")
    release = threading.Event()
    ran: list[str] = []

    async def main() -> dict[str, Any]:
        try:
            first, _first_beat = _start(_holder(release, ran, "first"), "exec-holds-the-thread")
            second, second_beat = _start(_holder(release, ran, "second"), "exec-waits-for-a-thread")
            await asyncio.sleep(0.3)
            assert ran == ["first"], f"the second worker started although the only thread was taken: {ran}"
            waiting = {
                "ran": list(ran),
                "waiting": second_beat.waiting_for_thread,
                # A record silent for 1000 s is not charged while its worker has no thread.
                "silence": events._worker_silence_s(1000.0, second_beat, events._LoopStallClock()),
            }
        finally:
            release.set()  # never leave a holder running, whatever failed above
        await asyncio.wait_for(asyncio.gather(first, second), timeout=10)
        waiting["after"] = (list(ran), second_beat.waiting_for_thread)
        waiting["silence_after"] = events._worker_silence_s(1000.0, second_beat, events._LoopStallClock())
        return waiting

    seen = asyncio.run(main())
    assert seen["ran"] == ["first"], "the second worker started although the only thread was taken"
    assert seen["waiting"] is True
    assert seen["silence"] is None, "time spent waiting for a thread was counted as silence"
    assert seen["after"] == (["first", "second"], False)
    assert seen["silence_after"] is not None and seen["silence_after"] < 5.0, "its silence starts when it starts"


def test_a_worker_stopped_while_it_waits_for_a_thread_never_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LIMIT_ENV, "1")
    release = threading.Event()
    ran: list[str] = []

    async def main() -> dict[str, Any]:
        try:
            first, _first_beat = _start(_holder(release, ran, "first"), "exec-runs")
            second, second_beat = _start(_holder(release, ran, "second"), "exec-stopped-in-the-queue")
            await asyncio.sleep(0.2)
            started = time.monotonic()
            await events._stop_worker(second_beat, second)
            stop_took = time.monotonic() - started
        finally:
            release.set()  # never leave a holder running, whatever failed above
        await asyncio.wait_for(first, timeout=10)
        await asyncio.sleep(0.2)
        assert ran == ["first"], f"a worker stopped before it had a thread still ran: {ran}"
        from thomas.server.chat_delegation_scheduler import scheduler_for_running_loop

        return {
            "stop_took": stop_took,
            "ran": list(ran),
            "heartbeat": worker_heartbeat("exec-stopped-in-the-queue"),
            "pool": scheduler_for_running_loop().snapshot(),
        }

    seen = asyncio.run(main())
    assert seen["ran"] == ["first"]
    assert seen["stop_took"] < 1.0, "the stop waited for a worker that had not started"
    assert seen["heartbeat"] is None
    assert seen["pool"]["queued"] == 0 and seen["pool"]["active"] == 0, seen["pool"]


def test_a_stop_that_comes_before_the_thread_starts_wins() -> None:
    """The heartbeat decides entry and stop under one lock: whichever comes first, the other knows."""
    from thomas.server.chat_delegation_emitter import WorkerHeartbeat

    stopped_first = WorkerHeartbeat("exec-a")
    assert stopped_first.request_stop() is False, "it had not entered"
    assert stopped_first.enter() is False, "a worker stopped before its thread started must never start"
    entered_first = WorkerHeartbeat("exec-b")
    assert entered_first.enter() is True
    assert entered_first.request_stop() is True, "it had entered, so it can only be asked to stop"


def test_a_worker_waiting_for_a_thread_says_so_stays_fresh_and_never_starts_once_its_record_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the only thread busy, a supervised worker waits. Its record says it waits for a free worker and keeps a
    fresh heartbeat, so the stale sweep leaves it alone. Once its record ends anyway (here the sweep, with no idle
    allowance), its watchdog stops it, and it never starts when the thread frees up (review of Step 17)."""
    from thomas.core import task_bot_runtime as rt
    from thomas.server import chat_delegation_runner as runner
    from thomas.server.chat_delegation_scheduler import scheduler_for_running_loop
    from thomas.server.stale_execution_sweep import sweep_stale_executions

    monkeypatch.setenv(LIMIT_ENV, "1")
    for name in ("_WORKER_FIRST_EVENT_TIMEOUT_S", "_WORKER_IDLE_EVENT_TIMEOUT_S"):
        monkeypatch.setattr(runner, name, 0.2)
    monkeypatch.setattr(runner, "_WORKER_WATCHDOG_GRACE_S", 0.0)
    monkeypatch.setattr(events, "_WAITING_REFRESH_S", 0.2, raising=False)
    eid = rt.create_execution(session_id="chat", summary="Write out.txt", repo_root=tmp_path)["execution_id"]
    for state in ("classified", "queued", "claimed", "executing"):
        rt.update_execution(eid, state=state, claimed_owner="nova", actor="nova", repo_root=tmp_path)
    release = threading.Event()
    ran: list[str] = []

    class Bot:
        id = name = "nova"

        def to_event_dict(self) -> dict[str, str]:
            return {}

    async def queued(_app: Any, **_kwargs: Any) -> None:
        ran.append("queued worker ran")

    async def main() -> dict[str, Any]:
        seen: dict[str, Any] = {}
        try:
            first, _beat = _start(_holder(release, [], "holder"), "exec-holds-the-only-thread")
            supervisor = asyncio.create_task(
                runner._run_agent_worker_supervised(
                    queued, None, execution_id=eid, specialist_id="reasoning", bot=Bot(),
                    emitter=_DelegationEmitter(lambda _event: asyncio.sleep(0)), repo_root=tmp_path, worker_kwargs={},
                )
            )  # fmt: skip
            await asyncio.sleep(2.5)  # more than ten times the watchdog's window
            record = rt.get_execution(eid, tmp_path)
            seen["waiting"] = (record["state"], record["progress_summary"], supervisor.done())
            seen["swept_while_fresh"] = await asyncio.to_thread(sweep_stale_executions, tmp_path, max_idle_s=2.0)
            seen["swept_anyway"] = await asyncio.to_thread(sweep_stale_executions, tmp_path, max_idle_s=0.0)
            await asyncio.wait_for(supervisor, timeout=10)
        finally:
            release.set()
        await asyncio.wait_for(first, timeout=10)
        await asyncio.sleep(1.0)
        seen["pool"] = scheduler_for_running_loop().snapshot()
        return seen

    seen = asyncio.run(main())
    state, progress, supervisor_done = seen["waiting"]
    assert (state, supervisor_done) == ("executing", False)
    assert progress.startswith("Waiting for a free worker"), f"the record did not say it was waiting: {progress!r}"
    assert seen["swept_while_fresh"] == 0, "the stale sweep failed a task that was only waiting for a thread"
    assert seen["swept_anyway"] == 1
    assert ran == [], "a worker whose record had ended started once a thread was free"
    assert worker_heartbeat(eid) is None
    assert seen["pool"]["queued"] == 0 and seen["pool"]["active"] == 0, seen["pool"]
