"""Move blocking work off the server's event loop, and keep the receipt.

Thomas's server is one aiohttp application on one event loop. Every request,
every websocket frame, every background maintenance loop and every Build child
agent is a coroutine on that single thread. So a synchronous call that takes
thirteen seconds does not cost its own caller thirteen seconds -- it costs the
whole server thirteen seconds, and every other tab, card and check goes silent
for exactly as long.

Measured 2026-09-24: the server stopped answering for over twenty seconds while
one git command ran, and started answering again the moment git finished.

:func:`off_loop` is the single boundary for that work. It hands the call to a
worker thread so the loop keeps turning, and -- because a fix nobody can see is
a fix that comes back -- it records how long the call actually took.
:func:`slowest_offloads` is that record; it is what the responsiveness test
reads, and what a future regression will show up in.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

# Anything slower than this had no business being on the loop in the first
# place. It is a reporting threshold, not a limit: nothing is cancelled or
# refused for crossing it, it is simply named in the log and in the receipts.
SLOW_CALL_BUDGET_S = 0.25

# How many distinct labels the receipt book holds. Labels are written by this
# module's callers and are a small fixed set, so this is a guard against a
# caller that builds a label from a path or an id, not a working limit.
_MAX_LABELS = 256

# Global receipt book -- initialized at import, before boot, because the first
# thing it must be able to record is boot itself. Bounded by _MAX_LABELS and
# holding only counters, so it needs no shutdown; tests clear it with
# reset_offload_receipts().
_lock = threading.Lock()
_receipts: dict[str, dict[str, Any]] = {}


def _record(label: str, seconds: float) -> None:
    with _lock:
        row = _receipts.get(label)
        if row is None:
            if len(_receipts) >= _MAX_LABELS:
                return
            row = {"label": label, "calls": 0, "total_s": 0.0, "max_s": 0.0, "over_budget": 0}
            _receipts[label] = row
        row["calls"] = int(row["calls"]) + 1
        row["total_s"] = float(row["total_s"]) + seconds
        row["max_s"] = max(float(row["max_s"]), seconds)
        if seconds > SLOW_CALL_BUDGET_S:
            row["over_budget"] = int(row["over_budget"]) + 1


async def off_loop(label: str, func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run ``func`` in a worker thread and return its result.

    ``label`` names the work, not the call -- "runtime_guard.refresh", not the
    repository it ran against -- so the receipts stay a fixed, readable set.

    Cancellation note: :func:`asyncio.to_thread` cannot interrupt a thread that
    is already inside a blocking call. Awaiting this can be cancelled, and the
    awaiting coroutine unblocks immediately, but the underlying work runs to
    completion in its thread. That is exactly the property that matters here:
    the loop is free either way.

    Timed with ``perf_counter``, not ``monotonic``: on Windows ``monotonic`` is
    ``GetTickCount64`` and advances in ~15.6 ms steps, so it recorded a measured
    1.2005 s call as 1.187 s about 15% of the time. A receipt that reads under
    the duration it measured cannot support a claim about that duration.
    """
    started = time.perf_counter()
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    finally:
        elapsed = time.perf_counter() - started
        _record(label, elapsed)
        if elapsed > SLOW_CALL_BUDGET_S:
            log.debug("off_loop %s took %.3fs (off the event loop)", label, elapsed)


def slowest_offloads(limit: int = 20) -> list[dict[str, Any]]:
    """The recorded work, slowest first. Read by tests and by health surfaces."""
    with _lock:
        rows = [dict(row) for row in _receipts.values()]
    for row in rows:
        calls = max(1, int(row.get("calls") or 1))
        row["mean_s"] = round(float(row.get("total_s") or 0.0) / calls, 4)
        row["max_s"] = round(float(row.get("max_s") or 0.0), 4)
        row["total_s"] = round(float(row.get("total_s") or 0.0), 4)
    rows.sort(key=lambda row: float(row.get("max_s") or 0.0), reverse=True)
    return rows[: max(1, int(limit or 1))]


def offload_summary() -> dict[str, Any]:
    """One compact object for a health payload: how much work was kept off the loop."""
    rows = slowest_offloads(limit=_MAX_LABELS)
    return {
        "labels": len(rows),
        "calls": sum(int(row.get("calls") or 0) for row in rows),
        "seconds_off_loop": round(sum(float(row.get("total_s") or 0.0) for row in rows), 3),
        "slowest": rows[:5],
    }


def reset_offload_receipts() -> None:
    """Forget every recorded call. For tests that measure one scenario."""
    with _lock:
        _receipts.clear()


__all__ = [
    "SLOW_CALL_BUDGET_S",
    "off_loop",
    "offload_summary",
    "reset_offload_receipts",
    "slowest_offloads",
]
