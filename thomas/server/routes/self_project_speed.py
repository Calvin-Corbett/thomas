"""Landed self-project wall-clock speed and overlapping teams from persisted timestamps."""

from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from thomas.core.landing_cost import landing_cost
from thomas.server.routes.self_project_listing_cache import read_record

STAGES = ("building", "checks", "second_look", "repair_rounds", "card_wait")


def _epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return stamp.timestamp() if stamp.tzinfo is not None else None
        except (ValueError, OverflowError):
            return None
    return None


_SUBMISSION = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_MAX_VERDICT_BYTES = 2_000_000


def _first_request(conversation: dict[str, Any]) -> float | None:
    turns = conversation.get("turns")
    for turn in turns if isinstance(turns, list) else []:
        if isinstance(turn, dict) and turn.get("role") == "user":
            return _epoch(turn.get("ts"))
    return None


def _landing(conversation: dict[str, Any], outbox: Path | None) -> float | None:
    project = conversation.get("thomas_project")
    if not isinstance(project, dict) or outbox is None:
        return None
    retirement = project.get("retirement")
    sid = project.get("submission") or (retirement.get("submission") if isinstance(retirement, dict) else None)
    if not isinstance(sid, str) or not _SUBMISSION.fullmatch(sid):
        return None
    path = outbox / f"{sid}.verdict.json"
    try:
        if path.stat().st_size > _MAX_VERDICT_BYTES:
            return None
        verdict = read_record(path)
    except (OSError, ValueError):
        return None
    if not isinstance(verdict, dict) or verdict.get("status") != "landed":
        return None
    stamp = verdict.get("ts")
    return float(stamp) if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else None


def _peak(intervals: list[tuple[float, float]], start: float, end: float) -> int:
    events = []
    for opened, closed in intervals:
        if closed > start and opened < end:
            events.extend(((max(opened, start), 1), (min(closed, end), -1)))
    concurrent = peak = 0
    for _, delta in sorted(events):  # close before open at the same instant
        concurrent += delta
        peak = max(peak, concurrent)
    return peak


def speed_scoreboard(
    conversations: dict[str, dict[str, Any]],
    timings: dict[str, dict[str, float | None]],
    outbox: Path | None,
    now: datetime,
    running: frozenset[str] | set[str] = frozenset(),
    step_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare landed projects by local landing day; never substitute hand-in for landing.

    With *step_rows* (the step log) each period also says what one landed change cost: Thomas's hours, prompt
    tokens, the share served from the provider's cache, and the machine's load.
    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = midnight.timestamp()
    week = (midnight - timedelta(days=7)).timestamp()
    current = now.timestamp()
    intervals: list[tuple[float, float]] = []
    landed: list[tuple[float, float, dict[str, float | None]]] = []
    active = set(running)
    for cid, conversation in conversations.items():
        opened = _first_request(conversation)
        if opened is None or opened > current:
            continue
        closed = _landing(conversation, outbox)
        if closed is not None and opened <= closed <= current:
            landed.append((closed, closed - opened, timings.get(cid, {})))
        # Handed-in copies stop at hand-in; only still-running greens extend to now.
        project = conversation.get("thomas_project")
        settled = _epoch(project.get("settled_at")) if isinstance(project, dict) else None
        ended = settled if settled is not None and opened <= settled <= current else None
        if closed is not None and opened <= closed <= current:
            ended = min(ended, closed) if ended is not None else closed
        if ended is not None:
            intervals.append((opened, ended))
        elif cid in active:
            intervals.append((opened, current))

    def period(start: float, end: float) -> dict[str, Any]:
        samples = [(elapsed, stages) for landed_at, elapsed, stages in landed if start <= landed_at < end]
        cost = landing_cost(step_rows, len(samples), start, end) if step_rows is not None else None
        if not samples:
            return {
                "median_seconds": None,
                "landed": 0,
                "steps": None,
                "peak_teams": _peak(intervals, start, end),
                "cost": cost,
            }
        median = statistics.median(elapsed for elapsed, _ in samples)
        # Share of the measured wall-clock for the projects that actually landed.
        totals = {key: 0.0 for key in STAGES}
        wall = sum(elapsed for elapsed, _ in samples)
        for elapsed, stages in samples:
            remaining = elapsed
            for key in STAGES:
                value = stages.get(key)
                seconds = min(remaining, max(0.0, value)) if isinstance(value, (int, float)) else 0.0
                totals[key] += seconds
                remaining -= seconds
        steps = {key: round(value / wall * 100, 1) for key, value in totals.items()} if wall else {}
        steps["unattributed"] = round((wall - sum(totals.values())) / wall * 100, 1) if wall else 0.0
        return {
            "median_seconds": round(median, 1),
            "landed": len(samples),
            "steps": steps,
            "peak_teams": _peak(intervals, start, end),
            "cost": cost,
        }

    current_period = period(today, current + 0.001)
    previous_period = period(week, today)
    current_median = current_period["median_seconds"]
    previous_median = previous_period["median_seconds"]
    faster_percent = (
        round(100 * (previous_median - current_median) / previous_median, 1)
        if current_median is not None and previous_median is not None and previous_median > 0
        else None
    )
    return {"today": current_period, "last_week": previous_period, "faster_percent": faster_percent}
