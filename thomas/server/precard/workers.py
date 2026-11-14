"""The threads checks and second looks run on, never the server's own (spec 2026-10-12 Part 1 item 5).

``asyncio.to_thread`` runs on the event loop's default executor, which the server's request handlers share, and a check
waiting for its turn held one of those threads the whole time. :data:`EXECUTOR` is eight threads of their own;
:func:`off_the_loop` runs a call there with a copy of the caller's context (the hand-in clocks ride on a context
variable), as ``asyncio.to_thread`` does.

Python's own shutdown waits (up to 300 s) only for the default executor's work, so a restart would leave a check here
running the old code beside the reloaded server, on the same green. The server's shutdown awaits :func:`drain`, which
waits as long for every call still here; a restart then shuts this executor down so its idle threads end
(``app_lifecycle._retire_check_threads``), and the re-imported module makes the next generation's.

A limit: one settle runs its check and then its second look on one of these threads, and a check may wait up to
``check.ADMISSION_WAIT_S`` for admission. While all eight wait (for admission or for a second-look turn), a ninth
hand-in waits in this executor's own first-come queue, outside the ledger's fewest-files-first line and before its
clocks start, and a second look for a change already checked can wait behind checks still waiting for room.
``scripts/praxis_timeline.py`` shows that wait as a ``precard_check`` phase longer than the clocks'
``check_for_hand_in``.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
import weakref
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, TypeVar

from thomas.server.capacity_ledger import NotAdmitted

T = TypeVar("T")
log = logging.getLogger(__name__)
CHECK_THREADS = 8
EXECUTOR = ThreadPoolExecutor(max_workers=CHECK_THREADS, thread_name_prefix="precard-check")
DRAIN_S = 300.0  # what Python's own shutdown gives the default executor's work
_in_flight: set[Future[Any]] = set()
_lock = threading.Lock()
_closed_admission: weakref.WeakSet[asyncio.AbstractEventLoop] = weakref.WeakSet()


class Restarting(NotAdmitted):
    """A check or second look that was not started because a restart is pending: the hand-in waits for the restart,
    with no strike, and is not a check that could not run (``hand_in_hold.wait_for_restart``)."""


def close_admission() -> None:
    """Prevent this loop from submitting new checks while existing workers drain."""
    with _lock:
        _closed_admission.add(asyncio.get_running_loop())


def admission_closed() -> bool:
    """Whether a restart pending on this loop holds new checks back; False outside a loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    with _lock:
        return loop in _closed_admission


def open_admission() -> None:
    """Let this loop submit checks again: a restart that was asked for was cancelled."""
    with _lock:
        _closed_admission.discard(asyncio.get_running_loop())


# Request tasks need not inherit serve_async's context. Keep overlapping
# generations in entry order so an older one retiring cannot revive itself.
_loops: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, list[threading.Event]] = weakref.WeakKeyDictionary()


def _loop_generation(loop: asyncio.AbstractEventLoop) -> threading.Event | None:
    generations = _loops.get(loop)
    return generations[-1] if generations else None


_stopping: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar("precard_stopping", default=None)
# The newest server generation's stop event, for a thread that has no loop and inherited no context.
_newest: threading.Event | None = None


def closing() -> bool:
    """Whether the newest server here is closing; safe to ask from any thread.

    ``generation_stopping`` answers for the caller's own context, and a thread that a request handed work to has none.
    A long read-only survey asks this between its steps and stops, so it cannot hold the shutdown open: on 2026-11-09
    two such surveys kept a finished server alive for 261 seconds, and the next server could not start until it left.
    """
    newest = _newest
    return newest is not None and newest.is_set()


@contextmanager
def generation(stopping: threading.Event) -> Iterator[None]:
    """Bind one server generation to its event loop and submitted check workers."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        _loops.setdefault(loop, []).append(stopping)
    token = _stopping.set(stopping)
    global _newest
    _newest = stopping
    try:
        yield
    finally:
        _stopping.reset(token)
        if loop is not None:
            generations = _loops.get(loop)
            if generations is not None:
                for index in range(len(generations) - 1, -1, -1):
                    if generations[index] is stopping:
                        del generations[index]
                        break
                if not generations:
                    _loops.pop(loop, None)


def generation_stopping() -> bool:
    """Whether work in this context belongs to a stopping server generation."""
    stopping = _stopping.get()
    if stopping is None:
        try:
            stopping = _loop_generation(asyncio.get_running_loop())
        except RuntimeError:
            pass
    return stopping is not None and stopping.is_set()


def stop_if_waiting() -> None:
    """End an admission wait only when its own generation is stopping."""
    if generation_stopping():
        from thomas.server import capacity_ledger

        raise capacity_ledger.NotAdmitted("this server is stopping", waited=True)


def _done(future: Future[Any]) -> None:
    with _lock:
        _in_flight.discard(future)


async def off_the_loop(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """``fn(*args, **kwargs)`` on the check threads, with this context, without holding the loop."""
    loop = asyncio.get_running_loop()
    stopping = _loop_generation(loop)
    if stopping is not None and _stopping.get() is None:
        # The settle task must retain this event after generation() exits: its
        # final durable hold runs through asyncio.to_thread, not this executor.
        _stopping.set(stopping)
    context = contextvars.copy_context()
    with _lock:
        if loop in _closed_admission:
            raise Restarting("Thomas is restarting; this check has not started", waited=True)
        future = EXECUTOR.submit(context.run, fn, *args, **kwargs)
        _in_flight.add(future)
    future.add_done_callback(_done)
    return await asyncio.wrap_future(future)


def active_calls() -> int:
    """Number of queued or running calls on the check threads."""
    with _lock:
        return len(_in_flight)


async def drain(timeout_s: float = DRAIN_S) -> bool:
    """Wait, at most *timeout_s* in all, for every call still queued or running here; True when none is left."""
    loop = asyncio.get_running_loop()
    ends = loop.time() + max(0.0, float(timeout_s))
    while True:
        with _lock:
            pending = set(_in_flight)
        if not pending:
            return True
        left = ends - loop.time()
        if left <= 0:
            log.warning("the server stops with %d check(s) or second look(s) still running", len(pending))
            return False
        await asyncio.wait([asyncio.wrap_future(future) for future in pending], timeout=left)


__all__ = [
    "CHECK_THREADS",
    "DRAIN_S",
    "EXECUTOR",
    "Restarting",
    "active_calls",
    "admission_closed",
    "close_admission",
    "closing",
    "drain",
    "generation",
    "generation_stopping",
    "off_the_loop",
    "open_admission",
    "stop_if_waiting",
]
