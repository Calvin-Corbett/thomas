"""A rolling record of this PC's load, for the sparklines on the Agents workspace.

``machine_load`` already runs the one background sampler and answers "what is the load now". It keeps one minute and
forgets the rest, so this keeps ten minutes of points for a chart. Nothing is written to disk.
"""

from __future__ import annotations

import asyncio
import collections
import threading
import time
from collections.abc import Callable
from typing import Any

from thomas.core import machine_load

INTERVAL_S = 5.0
SIZE = 120


def _clamp(value: float) -> float:
    return min(max(float(value), 0.0), 100.0)


class VitalsHistory:
    def __init__(self, size: int = SIZE) -> None:
        self._lock = threading.Lock()
        self._points: collections.deque[tuple[float, float, float]] = collections.deque(maxlen=size)

    def record(self, cpu: float, memory: float, ts: float | None = None) -> None:
        with self._lock:
            self._points.append((time.time() if ts is None else float(ts), _clamp(cpu), _clamp(memory)))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            points = list(self._points)
        latest = {"cpu": points[-1][1], "memory": points[-1][2], "ts": points[-1][0]} if points else None
        return {
            "interval_s": INTERVAL_S,
            "cpu": [p[1] for p in points],
            "memory": [p[2] for p in points],
            "latest": latest,
        }


HISTORY = VitalsHistory()


async def sample_loop(
    history: VitalsHistory,
    read: Callable[[], machine_load.Reading | None] = machine_load.latest,
    interval: float = INTERVAL_S,
) -> None:
    """Record one reading every ``interval`` seconds until cancelled. An unreadable reading is skipped, not recorded as 0."""
    while True:
        got = read()
        if got is not None:
            history.record(got.cpu, got.memory)
        await asyncio.sleep(interval)
