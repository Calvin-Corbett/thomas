"""Measure actual overlapping agent lifetimes, separate from request throughput."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def interval_concurrency(
    intervals: Mapping[str, tuple[float, float]], thresholds: Iterable[int] = (10, 50, 90, 100)
) -> dict[str, Any]:
    """Return peak overlap and time above each threshold for half-open intervals."""
    levels = tuple(sorted(set(thresholds)))
    events: list[tuple[float, int]] = []
    for start, end in intervals.values():
        if end > start:
            events.extend(((float(start), 1), (float(end), -1)))
    events.sort(key=lambda item: (item[0], item[1]))
    current = peak = 0
    peak_at = None
    above = {level: 0.0 for level in levels}
    for index, (moment, delta) in enumerate(events):
        current += delta
        if current > peak:
            peak, peak_at = current, moment
        if index + 1 < len(events):
            width = events[index + 1][0] - moment
            for level in levels:
                if current >= level:
                    above[level] += width
    return {
        "intervals": len(events) // 2,
        "peak": peak,
        "peak_at": peak_at,
        "span_s": round(events[-1][0] - events[0][0], 6) if events else 0.0,
        "seconds_at_or_above": {str(level): round(seconds, 6) for level, seconds in above.items()},
    }
