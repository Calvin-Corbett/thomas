"""Observed Praxis work intervals and dependency overlap.

Queue time is outside an agent's active interval. The overlap metric counts an
active owner only while at least one of its declared dependencies is active.
It is a measurement of recorded work, never a substitute for model receipts.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA = "praxis-timelines/1"
TOOL_FIELDS = ("tool", "start", "end", "outcome")
HOLD_FIELDS = ("entered", "released", "reason", "cycle_id", "generation", "outcome")


def sanitize_tools(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the timing and outcome of tool calls, never arguments or secrets."""
    return [{key: row.get(key) for key in TOOL_FIELDS} for row in rows]


def sanitize_holds(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{key: row.get(key) for key in HOLD_FIELDS} for row in rows]


def _intervals(value: object) -> list[tuple[float, float]]:
    if not isinstance(value, (list, tuple)):
        return []
    intervals: list[tuple[float, float]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        start, end = item
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(start)
            or not math.isfinite(end)
            or end <= start
        ):
            continue
        intervals.append((float(start), float(end)))
    return intervals


def dependency_overlap(
    intervals: Mapping[str, Sequence[tuple[float, float]]], dependencies: Mapping[str, Sequence[str]]
) -> dict[str, Any]:
    """Time-weighted number of active owners with active dependencies."""
    spans = {owner: _intervals(value) for owner, value in intervals.items()}
    points = sorted({time for intervals_for_owner in spans.values() for span in intervals_for_owner for time in span})
    integral = any_overlap = at_least_ten = 0.0
    peak = segments = 0
    for start, end in zip(points, points[1:]):
        width = end - start
        if width <= 0:
            continue
        midpoint = start + width / 2
        active = {
            owner
            for owner, intervals_for_owner in spans.items()
            if any(left <= midpoint < right for left, right in intervals_for_owner)
        }
        overlap = sum(bool(active.intersection(dependencies.get(owner, ()))) for owner in active)
        integral += overlap * width
        any_overlap += width if overlap else 0.0
        at_least_ten += width if overlap >= 10 else 0.0
        peak = max(peak, overlap)
        segments += 1
    span = points[-1] - points[0] if points else 0.0
    return {
        "integral_builder_seconds": round(integral, 6),
        "span_s": round(span, 6),
        "mean_concurrent": round(integral / span, 6) if span else 0.0,
        "peak": peak,
        "time_with_any_overlap_s": round(any_overlap, 6),
        "fraction_time_at_least_10": round(at_least_ten / span, 6) if span else 0.0,
        "segments": segments,
    }


def build_report(rows: Sequence[Mapping[str, Any]], *, now: float | None = None) -> dict[str, Any]:
    """Build a run timeline from engine-owned child state and activity spans."""
    spans: dict[str, list[tuple[float, float]]] = {}
    dependencies: dict[str, list[str]] = {}
    agents: list[dict[str, Any]] = []
    for row in rows:
        child_id = str(row.get("agent_id") or "")
        if not child_id or child_id in spans:
            continue
        active = _intervals(row.get("activity_intervals"))
        started = row.get("attempt_started_at")
        if row.get("state") == "running" and now is not None and isinstance(started, (int, float)):
            active.extend(_intervals([(started, now)]))
        spans[child_id] = active
        dependencies[child_id] = [str(dep) for dep in (row.get("dependencies") or []) if str(dep)]
        agents.append(
            {
                "agent_id": child_id,
                "state": str(row.get("state") or ""),
                "model_used": row.get("model_used"),
                "attempts": int(row.get("attempts") or 0),
                "active_s": round(sum(end - start for start, end in active), 6),
                "dependencies": dependencies[child_id],
            }
        )
    return {"schema": SCHEMA, "agents": agents, "dependency_overlap": dependency_overlap(spans, dependencies)}


__all__ = ["SCHEMA", "build_report", "dependency_overlap", "sanitize_holds", "sanitize_tools"]
