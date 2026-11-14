"""Delegated workers run on a thread pool of their own.

Workers used to run on the event loop's shared default pool, through ``asyncio.to_thread`` in
``_start_worker_thread``. A finishing worker waits for the server loop to deliver its "completed" notice, and that
notice's notification (``_DelegationEmitter._notify_lifecycle``) also needs a thread from the shared pool. That pool has
``min(32, cpu_count + 4)`` threads, 20 on a 16-core machine. Measured on dev 30395681 on such a machine: 20 workers
finishing together all recorded "completed", none of their 20 notices arrived, none of the 20 threads returned, and
anything else that needed the shared pool waited for ever; with 19 workers all 19 finished and reported.

So each event loop gets one ``DelegationScheduler``: a pool used only by delegated workers, of
``THOMAS_DELEGATION_MAX_ACTIVE_WORKERS`` threads (default 16). Notifications and every other use of the shared pool
never wait behind a worker, and the number of workers running at once is bounded and can be read
(``snapshot``). Further workers wait for a free thread in the order they came; a worker keeps its thread until it
returns. The worker's heartbeat says when it is waiting for a thread, so that wait is never counted as silence, and a
stop that comes while it waits means it never starts (``WorkerHeartbeat.enter`` and ``request_stop``).

Ported from refs/salvage/praxis-native-20260919/wt-native-scheduling (694a668b), without its admission groups. Its
``WorkerFence`` is the worker's heartbeat on today's code, which already carries the watchdog's stop.
"""

from __future__ import annotations

import asyncio
import contextvars
import os
import threading
import weakref
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

MAX_ACTIVE_WORKERS_ENV = "THOMAS_DELEGATION_MAX_ACTIVE_WORKERS"
DEFAULT_MAX_ACTIVE_WORKERS = 16
THREAD_NAME_PREFIX = "thomas-delegation-worker"


def max_active_workers() -> int:
    """The pool's size: THOMAS_DELEGATION_MAX_ACTIVE_WORKERS when it is a whole number of at least 1, otherwise 16."""
    raw = str(os.environ.get(MAX_ACTIVE_WORKERS_ENV) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_ACTIVE_WORKERS
    return value if value >= 1 else DEFAULT_MAX_ACTIVE_WORKERS


class DelegationScheduler:
    """One event loop's worker pool, and how many of its workers are waiting and running."""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, int(limit))
        self.executor = ThreadPoolExecutor(max_workers=self.limit, thread_name_prefix=THREAD_NAME_PREFIX)
        self._lock = threading.Lock()
        self.queued = 0
        self.active = 0
        self.peak_active = 0

    def start(
        self, fn: Callable[..., Any], *args: Any, on_wait: Callable[[], None] | None = None
    ) -> asyncio.Future[Any]:
        """Run ``fn(*args)`` on one of this pool's threads, in a copy of the caller's context, as ``asyncio.to_thread``
        does, and return a future of the running loop for its result.

        When every thread is taken, ``on_wait`` is called before the work is handed over, so the worker is known to be
        waiting for a thread before it could possibly start. Cancelling the future while the work still waits means it
        never runs."""
        with self._lock:
            waits = self.queued + self.active >= self.limit
            self.queued += 1
        job: Future[Any] | None = None
        try:
            if waits and on_wait is not None:
                on_wait()
            job = self.executor.submit(contextvars.copy_context().run, self._run, fn, args)
        finally:
            if job is None:  # nothing was handed over, so nothing waits
                with self._lock:
                    self.queued -= 1
        job.add_done_callback(self._forget_if_cancelled)
        return asyncio.wrap_future(job)

    def _run(self, fn: Callable[..., Any], args: tuple[Any, ...]) -> Any:
        with self._lock:
            self.queued -= 1
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
        try:
            return fn(*args)
        finally:
            with self._lock:
                self.active -= 1

    def _forget_if_cancelled(self, job: Future[Any]) -> None:
        if job.cancelled():  # cancelled while it waited for a thread: it never ran
            with self._lock:
                self.queued -= 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"limit": self.limit, "queued": self.queued, "active": self.active, "peak_active": self.peak_active}


_SCHEDULERS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, DelegationScheduler] = weakref.WeakKeyDictionary()
_SCHEDULERS_LOCK = threading.Lock()


def scheduler_for_running_loop() -> DelegationScheduler:
    """The running event loop's scheduler, made on first use with the limit in force at that moment."""
    loop = asyncio.get_running_loop()
    with _SCHEDULERS_LOCK:
        scheduler = _SCHEDULERS.get(loop)
        if scheduler is None:
            scheduler = DelegationScheduler(max_active_workers())
            _SCHEDULERS[loop] = scheduler
        return scheduler


__all__ = [
    "DEFAULT_MAX_ACTIVE_WORKERS",
    "MAX_ACTIVE_WORKERS_ENV",
    "THREAD_NAME_PREFIX",
    "DelegationScheduler",
    "max_active_workers",
    "scheduler_for_running_loop",
]
