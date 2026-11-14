"""The server answers while a long git command runs.

Measured 2026-09-24: Thomas's server stopped answering for over twenty seconds
while a git command ran, and started again the moment git finished. Two separate
defects produced that, and this file covers both.

1. ``subprocess.run(["git", ...], timeout=N)`` does not bound the call. On a
   timeout it kills the process it started and then drains the pipes, and a git
   reached through a launcher has already handed those pipe handles to a
   grandchild it spawned. Killing the launcher does not touch the grandchild, so
   the drain waits for it. Measured against ``cmd\\git.exe``: a 0.3-second
   timeout returned after 12.29 seconds.

2. Every one of those calls ran on the server's single event loop, so the bound
   would not have been enough on its own -- a call that is correctly bounded to
   four seconds still costs four seconds of total silence if it runs there.

The first test reproduces (1) without needing git at all: any process that
outlives its parent while holding the inherited pipe is the same shape, so the
child here is a Python one. The rest measure (2) the way the symptom was felt --
by asking the loop to wake a coroutine and timing how late it was, and by
counting how much other work is served while the slow call is still running.

Each of those is paired with a control that does the same thing with the fix
taken out, because a test that passes either way would not catch this coming
back. The controls are the two named ``..._on_the_loop_...``.

Two more cover the reading itself rather than the fix: that the lag reported for
a stall is the stall's own length, and that ``GET /api/landing-health`` publishes
both that figure and the work kept off the loop. A measurement nobody can read
is not a measurement anyone will act on.

The last three cover the two read-only git probes behind the server's own health
surfaces -- ``/api/landing-health`` and ``/api/system-map``, which the rows
``thomas.server.rows.server_diagnostics`` and ``thomas.server.rows.system_map`` register
through ``thomas.server.server_diagnostics_routes`` and ``thomas.server.system_map_routes``,
named here so a change to either runs this file. They are in worker
threads, so they cannot freeze the loop any more, but both used to carry the
unbounded timeout of (1), and every offload shares one thread pool: a probe that
never returns holds a worker that the runtime guard, the chat turn and the Code
endpoints all now depend on. They read git through the same bounded runner, and
a probe with a deadline of its own does not queue behind other git calls past it.
The build stamp a UI overlay write records is the third of that shape.

One covers ``POST /api/engine-actions``, the route of the row
``thomas.server.rows.engine_actions``, named here so a change to that row runs
this file, and which ran a whole maintenance cycle --
git calls, subprocess compiles, and up to four engines in one request -- where
it stood.

The last two cover the two loops that run for the life of the server, unasked:
the runtime guard's staleness check (three git calls, measured 169-196 ms warm
and 0.41-0.68 s loaded, on a 45-second cadence) and the consolidation sweep (27
git calls over 16 branches, measured 2.42 s of continuous blocking). Those are
the only blocking callers that need nobody to visit a page or send a message, so
they are the ones that could stop the server while it looked idle. Each runs the
real loop function for one tick with the tick's work replaced by a plain sleep,
and asks the same two questions as the tests above: did the loop keep its turns,
and did the work happen somewhere other than the main thread.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from thomas.core import code_issue_engine, git_process, landing_health, system_map
from thomas.core.event_loop_lag import EventLoopLag, watch_event_loop
from thomas.core.event_loop_offload import off_loop, reset_offload_receipts, slowest_offloads
from thomas.core.git_process import DRAIN_GRACE_S, TIMED_OUT_RETURNCODE, GitResult, run_git
from thomas.server import app_runtime_guard, consolidation_maintenance
from thomas.server.app_routes_task_ledger import build_task_ledger_handlers
from thomas.server.overlay import records as overlay_records
from thomas.server.routes.engine_actions_aiohttp import register_engine_actions_routes

# A child that spawns a grandchild and both linger. The grandchild inherits this
# process's stdout pipe, which is what makes killing the child insufficient.
_LINGERING_CHILD = (
    "import subprocess, sys, time; "
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(4)']); "
    "time.sleep(4)"
)
_BOUND_S = 0.4

# How long the blocking work runs in the lag tests below, and the lag the loop is
# allowed while it does. Work left on the loop lags by the whole of ``_TICK_S``,
# so the gap between the two is what is asserted. The budget is well clear of
# scheduler jitter: at 0.3 s a loaded machine measured 0.3046 s with the work
# correctly off the loop, and failed a fix that was working.
_TICK_S = 1.2
_LOOP_BUDGET_S = 0.5

# Either ``off_loop`` or a stand-in that does the work where it stands, so the
# two tests below differ in that one value and nothing else.
Runner = Callable[..., Awaitable[Any]]


def test_a_timeout_on_subprocess_run_is_not_an_upper_bound() -> None:
    """The defect itself, so the fix below is measured against something real.

    Skipped rather than failed if a platform does bound it: the claim being
    defended is the one in the next test, and this one exists to show what it is
    being defended against.
    """
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", _LINGERING_CHILD],
            capture_output=True,
            timeout=_BOUND_S,
        )
    elapsed = time.monotonic() - started
    if elapsed <= 2.0:
        pytest.skip(f"this platform held subprocess.run to {elapsed:.2f}s; the overrun is not reproducible here")
    assert elapsed > 2.0, f"a {_BOUND_S}s timeout took {elapsed:.2f}s -- the timeout bounded nothing"


def test_run_git_passes_safe_settings_without_exposing_secrets_in_mock_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    monkeypatch.setenv("THOMAS_TEST_SECRET", "sentinel-not-for-logs")

    def reject_process(*_args: object, **kwargs: object) -> None:
        seen.append(kwargs.get("env"))
        raise TypeError("unexpected mock process")

    monkeypatch.setattr(git_process.subprocess, "Popen", reject_process)
    with pytest.raises(TypeError, match="unexpected mock process"):
        run_git(["status"])
    assert len(seen) == 1
    env = seen[0]
    assert isinstance(env, dict)
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "sentinel-not-for-logs" not in repr(env)


def test_run_git_returns_inside_its_bound_even_when_the_pipes_are_held() -> None:
    """The fix: the caller is back within timeout + grace, whatever git leaves behind."""
    started = time.monotonic()
    result = run_git(["-c", _LINGERING_CHILD], timeout=_BOUND_S, git_binary=sys.executable)
    elapsed = time.monotonic() - started

    ceiling = _BOUND_S + DRAIN_GRACE_S + 1.5  # headroom for a loaded CI machine
    assert elapsed < ceiling, f"run_git took {elapsed:.2f}s against a {_BOUND_S}s bound"
    assert result.timed_out is True
    assert not result.ok
    assert result.message(), "a timed-out call must be able to explain itself to a caller"


@pytest.mark.asyncio
async def test_blocking_work_on_the_loop_is_what_stops_the_server_answering() -> None:
    """The control. Without this, the test below proves nothing."""
    monitor = EventLoopLag(budget_s=0.2)
    watcher = asyncio.create_task(watch_event_loop(interval_s=0.05, monitor=monitor))
    await asyncio.sleep(0.15)
    time.sleep(1.0)  # exactly what a synchronous git call does to the loop
    await asyncio.sleep(0.15)
    watcher.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watcher

    snapshot = monitor.snapshot()
    assert snapshot["max_lag_s"] > 0.5, f"a 1s block should show as lag, saw {snapshot}"
    assert snapshot["responsive"] is False


@pytest.mark.asyncio
async def test_the_same_work_through_off_loop_leaves_the_loop_responsive() -> None:
    """The fix, measured: identical blocking work, and the loop keeps its turns."""
    reset_offload_receipts()
    monitor = EventLoopLag(budget_s=_LOOP_BUDGET_S)
    watcher = asyncio.create_task(watch_event_loop(interval_s=0.05, monitor=monitor))
    await asyncio.sleep(0.15)
    await off_loop("test.blocking_call", time.sleep, _TICK_S)
    await asyncio.sleep(0.15)
    watcher.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watcher

    snapshot = monitor.snapshot()
    assert snapshot["max_lag_s"] < _LOOP_BUDGET_S, f"the loop was blocked anyway: {snapshot}"
    assert snapshot["responsive"] is True

    # And the work is on the record, so a regression is visible rather than felt.
    receipt = next(row for row in slowest_offloads() if row["label"] == "test.blocking_call")
    assert receipt["max_s"] >= _TICK_S
    assert receipt["over_budget"] == 1


@pytest.mark.asyncio
async def test_the_reported_lag_is_the_real_length_of_the_stall() -> None:
    """The figure is quoted back, so it has to be the duration and not a signal.

    ``/api/landing-health`` publishes ``max_lag_s`` and the watcher logs a
    warning naming it. "The server was blocked" is not the claim being made
    there -- "for this long" is.
    """
    stall_s = 0.75
    monitor = EventLoopLag(budget_s=0.2)
    watcher = asyncio.create_task(watch_event_loop(interval_s=0.05, monitor=monitor))
    await asyncio.sleep(0.15)
    time.sleep(stall_s)
    await asyncio.sleep(0.15)
    watcher.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watcher

    reported = monitor.snapshot()["max_lag_s"]
    # The sample that spans the stall asked for 0.05 s, so it is late by the
    # stall minus at most that. The upper bound is loose on purpose: a loaded
    # machine really is later, and over-reporting is not the failure mode here.
    assert stall_s - 0.12 <= reported <= stall_s + 0.4, f"a {stall_s}s stall was reported as {reported:.3f}s"


@pytest.mark.asyncio
async def test_landing_health_reports_the_loop_and_the_work_kept_off_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """``GET /api/landing-health`` carries both readings, so a regression is visible.

    ``seconds_off_loop`` is asserted against a known sleep to the millisecond,
    which is also what pins the clock: Windows' ``monotonic`` ticks every
    15.6 ms and would read this 0.3 s call as 0.297 s often enough to matter.
    """
    reset_offload_receipts()
    await off_loop("test.landing_probe", time.sleep, 0.3)

    class _Reading:
        def as_dict(self) -> dict[str, Any]:
            return {"severity": "ok", "commits_ahead": 0}

    monkeypatch.setattr(landing_health, "collect_landing_health", lambda: _Reading())
    handlers = build_task_ledger_handlers(web.Application(), require_api_access=lambda _request: None)
    response = await handlers["api_landing_health"](object())

    payload = json.loads(response.body)
    assert payload["severity"] == "ok", "the health reading itself must still come through unchanged"
    assert {"max_lag_s", "mean_lag_s", "budget_s", "responsive"} <= set(payload["event_loop"])

    kept_off = payload["off_loop"]
    assert kept_off["calls"] >= 1
    assert kept_off["seconds_off_loop"] >= 0.3, f"a 0.3s call was recorded as {kept_off['seconds_off_loop']}s"
    assert any(row["label"] == "test.landing_probe" for row in kept_off["slowest"]), kept_off


_POLL_TURNS = 8
_CALL_S = 1.2


async def _polls_served_during_a_call(runner: Runner) -> tuple[list[float], list[float]]:
    """Time a poller against one slow call, and return its polls and the call's window.

    The ordering is the measurement. The poller is started first, so its turns
    are already queued when the call begins; and each poll is timestamped
    against the call's own start and end rather than against the poll before it.
    Start the call first, or compare polls only to each other, and a blocking
    runner scores the same as a real one -- the block simply finishes before the
    poller's first turn, and every poll then lands after the call is over.

    The clock is ``perf_counter`` because the distinction being measured is
    sub-millisecond at one edge: with a blocking runner the first poll is served
    immediately *after* the call returns. ``time.monotonic`` on Windows advances
    in ~15.6 ms steps, so it reads that poll and the call's end as the same
    instant and the control cannot tell "just after" from "during".
    """
    served: list[float] = []
    window: list[float] = []

    async def pretend_request() -> None:
        for _ in range(_POLL_TURNS):
            await asyncio.sleep(0.05)
            served.append(time.perf_counter())

    async def long_git_call() -> None:
        window.append(time.perf_counter())
        await runner("test.long_git", time.sleep, _CALL_S)
        window.append(time.perf_counter())

    poller = asyncio.create_task(pretend_request())
    slow = asyncio.create_task(long_git_call())
    await asyncio.gather(poller, slow)

    assert len(served) == _POLL_TURNS, "the polling coroutine should have completed every turn"
    return served, window


def _served_during(served: list[float], started: float, ended: float) -> list[float]:
    """The polls that landed while the call was still in flight.

    Half-open on purpose: a poll that is served at the instant the call ends was
    waiting for it, not served during it.
    """
    return [stamp for stamp in served if started <= stamp < ended]


@pytest.mark.asyncio
async def test_a_call_left_on_the_loop_serves_nothing_until_it_finishes() -> None:
    """The control: the same shape with the offload removed, which is the old behaviour."""

    async def on_the_loop(_label: str, fn, *args) -> None:
        fn(*args)  # exactly what awaiting a synchronous call amounts to

    served, (started, ended) = await _polls_served_during_a_call(on_the_loop)

    during = _served_during(served, started, ended)
    assert during == [], f"{len(during)} polls were served during a call that holds the loop"


@pytest.mark.asyncio
async def test_a_request_is_served_during_a_long_blocking_call() -> None:
    """The user-visible claim: other work completes *while* the slow call is in flight."""
    reset_offload_receipts()
    served, (started, ended) = await _polls_served_during_a_call(off_loop)

    during = _served_during(served, started, ended)
    assert len(during) == _POLL_TURNS, (
        f"only {len(during)} of {_POLL_TURNS} polls were served inside the "
        f"{ended - started:.2f}s call -- the rest waited for it to finish"
    )
    gaps = [later - earlier for earlier, later in pairwise(served)]
    assert max(gaps) < 0.4, f"a turn waited {max(gaps):.2f}s on a call that should not have been on the loop"
    # The polls above are what catch a regression. This only has to show that the
    # call they were served during is the one that went through off_loop, so it
    # asks the receipt book for that and nothing finer.
    receipt = next(row for row in slowest_offloads() if row["label"] == "test.long_git")
    assert receipt["calls"] == 1, "the call the polls were served during must be the offloaded one"
    assert receipt["over_budget"] == 1, f"a {_CALL_S}s call must be recorded as over budget: {receipt}"


def _abandoned_after(seconds: float) -> GitResult:
    """What ``run_git`` returns for a git that had to be abandoned: no exception."""
    return GitResult(TIMED_OUT_RETURNCODE, "", "git did not finish and was abandoned", True, seconds)


def test_a_caller_with_a_deadline_does_not_queue_for_a_free_git_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """``slot_wait``: a probe with two seconds of budget must not wait twenty."""
    saturated = threading.BoundedSemaphore(1)
    saturated.acquire()  # the only permit is taken, as it is during a burst of git
    monkeypatch.setattr(git_process, "_spawn_slots", saturated)

    started = time.monotonic()
    result = git_process.run_git(["status"], timeout=30.0, slot_wait=0.2)
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"a caller that asked to wait 0.2s for a slot waited {elapsed:.2f}s"
    assert result.timed_out is True
    assert not result.ok
    assert "in flight" in result.message(), f"a saturated runner must say so: {result.message()!r}"


def test_the_landing_health_probe_reads_git_through_the_bounded_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint that reports responsiveness must not be able to hang on git."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed, so the probe never reaches a git call")

    calls: list[tuple[float, float | None]] = []

    def bounded_git(_args, *, cwd=None, timeout=15.0, slot_wait=None, **_kwargs) -> GitResult:
        calls.append((float(timeout), slot_wait))
        return _abandoned_after(float(timeout))

    monkeypatch.setattr(landing_health, "run_git", bounded_git)
    health = landing_health.collect_landing_health()

    assert calls, "the probe did not read git through run_git"
    assert health.severity == landing_health.SEVERITY_UNKNOWN
    assert health.commits_ahead is None, "a reading that could not read git must not invent numbers"
    assert all(seconds <= landing_health.GIT_COMMAND_TIMEOUT_SECONDS for seconds, _slot in calls)
    assert all(slot is not None for _seconds, slot in calls), "the probe's own deadline must cap the slot wait"


def test_the_system_map_reader_reports_an_abandoned_git_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/api/system-map`` reads git the same bounded way, and names what it lost."""

    def bounded_git(_args, *, cwd=None, timeout=15.0, slot_wait=None, **_kwargs) -> GitResult:
        return _abandoned_after(float(timeout))

    monkeypatch.setattr(system_map, "run_git", bounded_git)
    reader = system_map._GitReader(Path.cwd(), budget_seconds=2.0)

    assert reader.run("status", "--porcelain") is None
    assert reader.failures == ["git status"]


def test_the_overlay_build_stamp_reads_git_once_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A UI overlay write stamps the build's sha, so that read is bounded too.

    ``POST /api/ui/overlay/records`` already hands its write to a worker thread,
    so this could not freeze the loop -- but it read git through the timeout that
    bounds nothing, from a thread out of the one shared pool.
    """
    calls: list[tuple[float, float | None]] = []

    def abandoned_git(_args, *, cwd=None, timeout=15.0, slot_wait=None, **_kwargs) -> GitResult:
        calls.append((float(timeout), slot_wait))
        return _abandoned_after(float(timeout))

    monkeypatch.setattr(overlay_records, "run_git", abandoned_git)
    monkeypatch.setattr(overlay_records, "_short_sha", None)

    assert overlay_records._git_short_sha() is None, "an abandoned git must not become a build stamp"
    assert calls, "the stamp did not read git through run_git"
    assert calls[0][0] <= 5.0
    assert calls[0][1] is not None, "a stamp is not worth twenty seconds of queueing for a git slot"

    overlay_records._git_short_sha()
    assert len(calls) == 2, "a git that could not answer once must not be memoised as 'no sha'"

    def quick_git(_args, *, cwd=None, timeout=15.0, slot_wait=None, **_kwargs) -> GitResult:
        calls.append((float(timeout), slot_wait))
        return GitResult(0, "abc1234\n", "", False, 0.01)

    monkeypatch.setattr(overlay_records, "run_git", quick_git)
    assert overlay_records._git_short_sha() == "abc1234"
    settled = len(calls)
    assert overlay_records._git_short_sha() == "abc1234"
    assert len(calls) == settled, "the sha of the running build is read once per process"
    assert overlay_records.birth_base()["git"] == "abc1234"


class _CapturingRouter:
    """Just enough of ``app.router`` to catch the handler that gets registered."""

    def __init__(self) -> None:
        self.posts: dict[str, Any] = {}

    def add_post(self, path: str, handler: Any) -> None:
        self.posts[path] = handler


class _CapturingApp:
    def __init__(self) -> None:
        self.router = _CapturingRouter()


async def _engine_action_payload(_request: Any) -> dict[str, Any]:
    return {"engine": "code_issue_engine", "action": "run"}


@pytest.mark.asyncio
async def test_a_manual_engine_run_is_not_done_on_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """``POST /api/engine-actions`` runs an entire maintenance cycle per request.

    ``workspace_sync_engine`` shells out to git repeatedly -- bounded now, but
    still seconds of disk work -- and ``engine: "all"`` runs four cycles in one
    request, so this is the largest single piece of blocking work reachable from
    a route. Take the ``off_loop`` out and the cycle runs on the main thread,
    which is exactly what this asserts against.
    """
    reset_offload_receipts()
    ran_on: list[str] = []

    class _Engine:
        def run_cycle_once(self, *, reason: str, force: bool) -> dict[str, Any]:
            ran_on.append(threading.current_thread().name)
            return {"ok": True, "reason": reason, "force": force}

    monkeypatch.setattr(code_issue_engine, "get_code_issue_engine", lambda: _Engine())

    app = _CapturingApp()
    register_engine_actions_routes(
        app,
        require_api_access=lambda _request: None,
        read_json=_engine_action_payload,
    )
    handler = app.router.posts["/api/engine-actions"]
    response = await handler(object())

    assert response.status == 200
    assert ran_on, "the endpoint never reached the engine"
    assert ran_on[0] != threading.main_thread().name, (
        f"the cycle ran on {ran_on[0]!r}, so the loop was held for the whole of it"
    )
    labels = {row["label"] for row in slowest_offloads()}
    assert "engine_actions.code_issue_engine" in labels, f"the cycle is not on the record: {labels}"


@pytest.mark.asyncio
async def test_the_runtime_guard_check_does_not_stop_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sweep item 1: the staleness check runs every 45 s for the life of the server.

    It is three git subprocesses against the repository -- nothing a request
    asked for, and nobody has to be using Thomas for it to run. Measured 169-196
    ms warm and 0.41-0.68 s under load, and every millisecond used to come out of
    the loop on a cadence. This runs one real tick of ``_runtime_guard_loop``
    with the refresh replaced by a sleep of the same shape, and requires both
    that the loop kept its turns and that the refresh was not on the main thread.
    """
    reset_offload_receipts()
    ran_on: list[str] = []

    def _slow_refresh(_app: Any) -> dict[str, Any]:
        ran_on.append(threading.current_thread().name)
        time.sleep(_TICK_S)
        return {"state": "ok"}

    monkeypatch.setattr(app_runtime_guard, "_runtime_guard_refresh", _slow_refresh)

    monitor = EventLoopLag(budget_s=_LOOP_BUDGET_S)
    watcher = asyncio.create_task(watch_event_loop(interval_s=0.05, monitor=monitor))
    await asyncio.sleep(0.15)

    # The loop never returns on its own, so take exactly one tick and cancel it
    # in the sleep that follows -- the same way shutdown ends it. Waiting on the
    # receipt rather than on a clock is what makes "one tick" deterministic: the
    # receipt is written in a ``finally``, when the tick is done.
    guard = asyncio.create_task(app_runtime_guard._runtime_guard_loop(web.Application()))
    deadline = time.monotonic() + 10.0
    while not any(row["label"] == "runtime_guard.refresh" for row in slowest_offloads()):
        assert time.monotonic() < deadline, "the guard never completed a tick"
        await asyncio.sleep(0.02)
    guard.cancel()
    with pytest.raises(asyncio.CancelledError):
        await guard

    watcher.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watcher

    snapshot = monitor.snapshot()
    assert snapshot["max_lag_s"] < _LOOP_BUDGET_S, f"the guard tick held the loop: {snapshot}"
    assert snapshot["responsive"] is True
    assert ran_on[0] != threading.main_thread().name, (
        f"the check ran on {ran_on[0]!r}, so a background check nobody asked for was the server's only work"
    )
    # On the record under the name the health surface publishes, and for the
    # length it really took -- a receipt shorter than the work it measured could
    # not show this coming back.
    receipt = next(row for row in slowest_offloads() if row["label"] == "runtime_guard.refresh")
    assert receipt["max_s"] >= _TICK_S, f"the tick is recorded as {receipt['max_s']}s, shorter than it ran"


@pytest.mark.asyncio
async def test_the_consolidation_sweep_does_not_stop_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sweep item 3: the branch sweep is the largest single tick on a timer.

    Measured 2.42 s of continuous blocking -- 27 git calls over 16 local
    branches, two of them diffs. On the loop that is 2.42 s in which no request
    is served, and it is reached by nothing a person did. ``max_cycles=1`` and
    the injected ``audit_fn``/``sleep_fn`` are the loop's own test seams, so
    what runs here is the shipped loop body and not a copy of it.
    """
    reset_offload_receipts()
    monkeypatch.setattr(consolidation_maintenance, "maintenance_enabled", lambda: True)
    ran_on: list[str] = []

    def _slow_audit() -> dict[str, Any]:
        ran_on.append(threading.current_thread().name)
        time.sleep(_TICK_S)
        return {"ok": True}

    monitor = EventLoopLag(budget_s=_LOOP_BUDGET_S)
    watcher = asyncio.create_task(watch_event_loop(interval_s=0.05, monitor=monitor))
    await asyncio.sleep(0.15)

    cycles = await consolidation_maintenance.consolidation_maintenance_loop(
        startup_delay_s=0.0,
        audit_fn=_slow_audit,
        sleep_fn=asyncio.sleep,
        max_cycles=1,
    )

    watcher.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watcher

    assert cycles == 1
    snapshot = monitor.snapshot()
    assert snapshot["max_lag_s"] < _LOOP_BUDGET_S, f"the sweep held the loop: {snapshot}"
    assert snapshot["responsive"] is True
    assert ran_on[0] != threading.main_thread().name, (
        f"the sweep ran on {ran_on[0]!r}, so the server went quiet for the length of it"
    )
    receipt = next(row for row in slowest_offloads() if row["label"] == "consolidation.audit")
    assert receipt["max_s"] >= _TICK_S


def test_resetting_the_board_memo_makes_the_next_read_derive_it_again(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The memo that keeps chat turns off the board must still yield to a reset.

    conftest resets it before every test: a stub for ``list_executions`` is never
    reached if an earlier read of the same root, with the same file signature, is
    still being served.
    """
    from thomas.server import chat_delegation_session as delegation

    board = tmp_path / "runtime" / "coordination" / "task_bots"
    board.mkdir(parents=True)
    (board / "exec-1.json").write_text("{}", encoding="utf-8")
    derived: list[str] = []

    def _rows(label: str) -> Callable[..., list[dict[str, Any]]]:
        def _list(_root: Path, **_kwargs: Any) -> list[dict[str, Any]]:
            derived.append(label)
            return [{"execution_id": label}]

        return _list

    monkeypatch.setattr(delegation.task_bot_runtime, "runtime_dir", lambda _root=None: board)
    monkeypatch.setattr(delegation, "_BOARD_TTL_S", 60.0)
    monkeypatch.setattr(delegation.task_bot_runtime, "list_executions", _rows("first"))
    assert delegation.board_rows(tmp_path) == [{"execution_id": "first"}]

    monkeypatch.setattr(delegation.task_bot_runtime, "list_executions", _rows("second"))
    assert delegation.board_rows(tmp_path) == [{"execution_id": "first"}], "an unmoved board is served from the memo"

    delegation.reset_board_cache()
    assert delegation.board_rows(tmp_path) == [{"execution_id": "second"}]
    assert derived == ["first", "second"]
