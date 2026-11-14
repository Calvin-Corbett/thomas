"""How long the event loop was blocked, measured from inside it.

A claim that the server stays responsive is only worth what measures it. This
does the measuring the same way the symptom was felt: it asks to be woken every
quarter second and reports how late it actually was. A coroutine that sleeps
0.25 s and wakes 20 s later was not slow -- it was never scheduled, because
something else held the only thread there is.

That number is the honest definition of "the server stopped answering", because
a request handler cannot start until the loop can schedule it either. The
watcher is cheap enough to leave running: one timer wake-up and one subtraction
per sample.

Read :func:`lag_snapshot` for the running figure, and see
``thomas/core/event_loop_offload.py`` for the boundary that keeps it low.

The watcher can only report a stall once the loop runs again, so a loop that
never runs again is never reported. :func:`start_freeze_watch` covers that case
from a thread of its own: once the loop has gone :data:`DEFAULT_FREEZE_DUMP_S`
without waking the watcher, it writes every thread's stack to a
``loop-freeze-*.txt`` beside the server's log, once per freeze, so a freeze
names the call that caused it.
"""

from __future__ import annotations

import asyncio
import faulthandler
import logging
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# How often to ask to be woken. Small enough to catch a stall a person would
# notice, large enough to cost nothing.
DEFAULT_SAMPLE_INTERVAL_S = 0.25
# Lag above this is a stall worth a log line. A browser tolerates a quarter
# second; half a second is already visible in a streaming chat.
DEFAULT_LAG_BUDGET_S = 0.5
# A loop that has not run for this long is frozen, not slow: the longest stall
# that recovered on 2026-10-23 was 17.7 s, and the freezes that did not recover
# never woke the watcher again.
DEFAULT_FREEZE_DUMP_S = 30.0
# How often the freeze thread looks; a dump lands within this of the threshold.
DEFAULT_FREEZE_CHECK_S = 5.0


class EventLoopLag:
    """Running lag figures for one event loop.

    Deliberately not a histogram: the maximum is the number that matters, since
    one twenty-second stall is the whole complaint and an average over hours
    would hide it completely.
    """

    def __init__(self, budget_s: float = DEFAULT_LAG_BUDGET_S) -> None:
        self.budget_s = max(0.01, float(budget_s))
        self._lock = threading.Lock()
        self._samples = 0
        self._total_s = 0.0
        self._max_s = 0.0
        self._over_budget = 0
        self._worst_at = 0.0
        self._last_wake = 0.0  # perf_counter of the watcher's last turn; 0.0 while no watcher runs

    def woke(self) -> None:
        """The watcher just had a turn on the loop."""
        with self._lock:
            self._last_wake = time.perf_counter()

    def stopped(self) -> None:
        """No watcher runs any more, so its silence says nothing about the loop."""
        with self._lock:
            self._last_wake = 0.0

    def since_wake(self) -> float:
        """Seconds since the watcher last had a turn; 0.0 when no watcher runs."""
        with self._lock:
            last = self._last_wake
        return time.perf_counter() - last if last else 0.0

    def observe(self, lag_s: float) -> None:
        """Record one sample: how much later than asked the loop woke us."""
        lag = max(0.0, float(lag_s))
        with self._lock:
            self._samples += 1
            self._total_s += lag
            if lag > self._max_s:
                self._max_s = lag
                self._worst_at = time.time()
            if lag > self.budget_s:
                self._over_budget += 1

    def snapshot(self) -> dict[str, Any]:
        """The figures so far, safe to read from any thread."""
        with self._lock:
            samples = self._samples
            total = self._total_s
            worst = self._max_s
            over = self._over_budget
            worst_at = self._worst_at
        return {
            "samples": samples,
            "max_lag_s": round(worst, 4),
            "mean_lag_s": round(total / samples, 4) if samples else 0.0,
            "budget_s": self.budget_s,
            "over_budget": over,
            "responsive": samples > 0 and worst <= self.budget_s,
            "worst_at_epoch": round(worst_at, 3) if worst_at else 0.0,
        }

    def reset(self) -> None:
        with self._lock:
            self._samples = 0
            self._total_s = 0.0
            self._max_s = 0.0
            self._over_budget = 0
            self._worst_at = 0.0


# Global lag monitor -- initialized at import so the figures cover the whole
# process life. The sampling TASK that feeds it is started in the server's
# on_startup (start_loop_watch) and cancelled in on_cleanup; this object holds
# only counters and needs no shutdown of its own.
_monitor = EventLoopLag()


def lag_monitor() -> EventLoopLag:
    """The process-wide monitor the server's watcher feeds."""
    return _monitor


def lag_snapshot() -> dict[str, Any]:
    """Current lag figures for the server's loop."""
    return _monitor.snapshot()


async def watch_event_loop(
    *,
    interval_s: float = DEFAULT_SAMPLE_INTERVAL_S,
    monitor: EventLoopLag | None = None,
    samples: int | None = None,
) -> int:
    """Sample loop lag until cancelled. Returns the number of samples taken.

    ``samples`` bounds the run so a test can take a known number and assert on
    them; production passes nothing and it runs for the life of the server.
    """
    target = monitor if monitor is not None else _monitor
    interval = max(0.01, float(interval_s))
    taken = 0
    target.woke()
    try:
        while samples is None or taken < int(samples):
            # ``perf_counter``, not ``monotonic``: on Windows ``monotonic`` is
            # ``GetTickCount64`` and advances in ~15.6 ms steps, so it quantizes every
            # lag reading to a tick. ``max_lag_s`` is quoted back through
            # /api/landing-health as a duration, and the same clock is used for the
            # off-loop receipts (thomas/core/event_loop_offload.py, lines 78-81).
            # The loop's own timer still has that granularity, so a few milliseconds
            # of the figure below is scheduler jitter -- which is real lateness, and
            # belongs in it.
            before = time.perf_counter()
            await asyncio.sleep(interval)
            target.woke()
            lag = (time.perf_counter() - before) - interval
            target.observe(lag)
            taken += 1
            if lag > target.budget_s:
                # Named at warning because this is the shape of the outage: not an
                # error anywhere, just a loop that could not get a turn.
                log.warning(
                    "Event loop was blocked for %.2fs (budget %.2fs) -- something ran synchronously on it",
                    lag,
                    target.budget_s,
                )
    finally:
        target.stopped()  # a cancelled watcher's silence is not a frozen loop
    return taken


def freeze_dump_path(when: float | None = None) -> Path:
    """Where a freeze's stacks go: beside ``THOMAS_LOG_FILE``, else the temp folder."""
    log_file = os.environ.get("THOMAS_LOG_FILE")
    folder = Path(log_file).parent if log_file else Path(tempfile.gettempdir())
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(when))
    return folder / f"loop-freeze-{stamp}.txt"


def dump_stacks(path: Path, stalled_s: float, *, headline: str | None = None) -> Path:
    """Write the main thread's stack, then every thread's, to *path*, under *headline* or the freeze's own.

    ``faulthandler`` writes at most 100 threads, newest first, so beside a busy fleet (160 threads on 2026-10-23) it
    left out the main thread, where the server's loop runs: that one is written first, from ``sys._current_frames``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    main = threading.main_thread().ident
    frame = sys._current_frames().get(main) if main is not None else None
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(headline or f"The event loop has not run for {stalled_s:.0f} s. Every thread's stack follows.")
        handle.write("\n\n")
        if frame is not None:
            handle.write(f"Main thread {main:#018x} (most recent call last):\n")
            handle.write("".join(traceback.format_stack(frame)))
            handle.write("\nAll threads, at most 100 (most recent call first):\n\n")
        handle.flush()
        faulthandler.dump_traceback(file=handle, all_threads=True)
    return path


SHUTDOWN_DUMP_S = 20.0
SHUTDOWN_DUMPS = 15


def watch_shutdown(
    every_s: float = SHUTDOWN_DUMP_S, *, folder: Path | None = None, limit: int = SHUTDOWN_DUMPS
) -> threading.Event:
    """While a shutdown is still going after *every_s*, write where every thread is, and again each *every_s*.

    Nothing times the steps of a shutdown, and one that waits says nothing: on 2026-11-09 the caged server wrote its
    exit record at 17:18:06 and its process ended at 17:20:59, with the port closed and no line logged between. This
    writes ``shutdown-<pid>-<number>-<seconds>s.txt`` beside the freeze dumps, at most *limit* of them, from a thread that ends
    with the process. Set the event it returns to stop it sooner; a shutdown that ends in time writes nothing.
    """
    done = threading.Event()
    began = time.monotonic()
    where = folder or freeze_dump_path().parent

    def watch() -> None:
        for number in range(1, max(0, limit) + 1):
            if done.wait(every_s):
                return
            waited = time.monotonic() - began
            path = where / f"shutdown-{os.getpid()}-{number:02d}-{waited:.0f}s.txt"
            try:
                dump_stacks(
                    path,
                    waited,
                    headline=f"Thomas has been shutting down for {waited:.0f} s. Every thread's stack follows.",
                )
            except OSError:
                log.debug("the shutdown's stacks could not be written to %s", path, exc_info=True)
                return
            log.warning("Thomas has been shutting down for %.0f s; where every thread is: %s", waited, path)

    threading.Thread(target=watch, name="thomas-shutdown-watch", daemon=True).start()
    return done


def _watch_for_freezes(monitor: EventLoopLag, stall_s: float, check_s: float, stop: threading.Event) -> None:
    dumped = False
    while not stop.wait(check_s):
        stalled = monitor.since_wake()
        if stalled < stall_s:
            dumped = False  # the loop ran again: the next freeze gets its own dump
            continue
        if dumped:
            continue
        dumped = True
        try:
            path = dump_stacks(freeze_dump_path(), stalled)
        except OSError:
            continue
        # After the file: a logging lock may be what the loop is stuck behind.
        log.error("The event loop has not run for %.0f s; every thread's stack is in %s", stalled, path)


def start_freeze_watch(
    monitor: EventLoopLag | None = None,
    *,
    stall_s: float = DEFAULT_FREEZE_DUMP_S,
    check_s: float = DEFAULT_FREEZE_CHECK_S,
) -> threading.Event:
    """Watch *monitor*'s watcher from a daemon thread; set the returned event to stop it."""
    stop = threading.Event()
    threading.Thread(
        target=_watch_for_freezes,
        args=(monitor if monitor is not None else _monitor, float(stall_s), float(check_s), stop),
        name="event-loop-freeze-watch",
        daemon=True,
    ).start()
    return stop


_freeze_watch: threading.Event | None = None


def start_loop_watch(store: Any | None = None, *, key: str = "event_loop_lag_task") -> asyncio.Task[int]:
    """Start the watcher on the running loop, parking the task in ``store``.

    ``store`` is the aiohttp application (or any mapping) so cleanup can cancel
    the task; it is optional so a test can start a bare watcher. The first call
    also starts this process's freeze watch (:func:`start_freeze_watch`).
    """
    global _freeze_watch
    task = asyncio.create_task(watch_event_loop(), name="event-loop-lag-watch")
    if store is not None:
        store[key] = task
    if _freeze_watch is None:
        _freeze_watch = start_freeze_watch()
        # Beside it, the thread that names what had the main thread during a block of most of a second.
        from thomas.core import event_loop_blame

        event_loop_blame.start(_monitor.since_wake)
    return task


__all__ = [
    "DEFAULT_FREEZE_CHECK_S",
    "DEFAULT_FREEZE_DUMP_S",
    "DEFAULT_LAG_BUDGET_S",
    "DEFAULT_SAMPLE_INTERVAL_S",
    "EventLoopLag",
    "dump_stacks",
    "watch_shutdown",
    "freeze_dump_path",
    "lag_monitor",
    "lag_snapshot",
    "start_freeze_watch",
    "start_loop_watch",
    "watch_event_loop",
]
