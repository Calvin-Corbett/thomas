"""What the check clocks say, how busy each day was, and whether a pass line is met (``scripts/praxis_timeline.py``).

The clocks are ``thomas/server/precard/clocks.py``'s records. Every stage is summarized by its name, so a stage that
a later change adds or renames still counts. A check "under load" is one of at most :data:`PART1_MAX_FILES` selected
files that started within :data:`TOGETHER_S` of at least ``TOGETHER_N - 1`` other checks: the spec's "6 hand-ins
arriving together". ``max_checks_at_once`` counts checks that are waiting for their turn as well as running ones (the
``check_for_hand_in`` stage includes the wait); ``max_running_at_once`` counts only those inside their turn, the
``in_slot`` stage. The building share is launch to the last hand-in, the definition behind the 32% baseline; the
share of Build run time is reported beside it.

A clocks line and a project row are files a Build team can write, so a record that is not a mapping, a time that is not
readable and a number that is not a finite number are stepped over and never raised on: they were not measured.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, tzinfo
from typing import Any

from scripts.praxis.timeline_sources import iso_to_epoch
from scripts.praxis.timeline_totals import med, percentile

CHECK_STAGE = "check_for_hand_in"
SLOT_STAGE = "in_slot"
TOGETHER_S = 60.0
TOGETHER_N = 6
PART1_MAX_FILES = 120
CHECK_P90_TARGET_S = 240.0
FLOOR_BYTES = 10 * 1024**3
BUSY_TARGET = 0.75


def _number(value: object) -> float | None:
    """A recorded number as a float; a bool, a string, nan, inf and a number too big for a float are not recorded."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _seconds(value: object) -> float | None:
    """A recorded length of time: a number that is not negative."""
    number = _number(value)
    return number if number is not None and number >= 0 else None


def _when(value: object) -> float | None:
    """Seconds since the epoch for a recorded time, or None when it is missing or not a time."""
    return None if isinstance(value, bool) else _number(iso_to_epoch(value))


def _measured(value: object) -> Any:
    """The value itself when it is a recorded number, else None, so a pass line says it measured nothing."""
    return value if _number(value) is not None else None


def _dicts(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _stage_spans(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stages = record.get("stages")
    if not isinstance(stages, dict):
        return {}
    return {str(name): stage for name, stage in stages.items() if isinstance(stage, dict)}


def _checks(records: list[dict[str, Any]]) -> list[tuple[float, float, int]]:
    """(start, seconds, selected files or -1) of every record's check."""
    found = []
    for record in records:
        stage = _stage_spans(record).get(CHECK_STAGE)
        if stage is None:
            continue
        took, start = _seconds(stage.get("seconds")), _when(stage.get("start"))
        if took is None or start is None:
            continue
        files = record.get("selected_files")
        found.append((start, took, files if isinstance(files, int) and not isinstance(files, bool) else -1))
    return found


def _slots(records: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """(start, end) of every record's turn at the one place the check runs in (its ``in_slot`` stage)."""
    found = []
    for record in records:
        stage = _stage_spans(record).get(SLOT_STAGE)
        if stage is None:
            continue
        took, start = _seconds(stage.get("seconds")), _when(stage.get("start"))
        if took is not None and start is not None:
            found.append((start, start + took))
    return found


def _most_at_once(intervals: list[tuple[float, float]]) -> int:
    edges = sorted([(start, 1) for start, _ in intervals] + [(end, -1) for _, end in intervals])
    running = most = 0
    for _, step in edges:
        running += step
        most = max(most, running)
    return most


def clocks_summary(records: list[dict[str, Any]], *, since: float, until: float) -> dict[str, Any]:
    window = []
    for record in _dicts(records):
        began = _when(record.get("started_at"))
        if began is not None and since <= began < until:
            window.append(record)
    seconds: dict[str, list[float]] = {}
    for record in window:
        for name, stage in _stage_spans(record).items():
            took = _seconds(stage.get("seconds"))
            if took is not None:
                seconds.setdefault(name, []).append(took)
    stages = {
        name: {
            "n": len(values),
            "median_s": med(values),
            "p90_s": percentile(values, 0.9),
            "max_s": round(max(values), 3),
            "sum_s": round(sum(values), 1),
        }
        for name, values in sorted(seconds.items())
    }
    checks = _checks(window)
    loaded = [
        took
        for number, (start, took, files) in enumerate(checks)
        if 0 <= files <= PART1_MAX_FILES
        and sum(1 for other, (s, _, _) in enumerate(checks) if other != number and abs(s - start) <= TOGETHER_S)
        >= TOGETHER_N - 1
    ]
    disk = [
        int(value)
        for record in window
        for key, value in record.items()
        if key.startswith("free_disk_") and key.endswith("_bytes") and _number(value) is not None
    ]
    return {
        "records": len(window),
        "stages": stages,
        "outcomes": dict(Counter(str(record.get("outcome") or "") for record in window)),
        "check_states": dict(Counter(str(r["check_state"]) for r in window if r.get("check_state"))),
        "check_causes": dict(Counter(str(r["check_cause"]) for r in window if r.get("check_cause"))),
        "check": {
            "n": len(checks),
            "p90_s": percentile([took for _, took, _ in checks], 0.9),
            "under_load_n": len(loaded),
            "p90_under_load_s": percentile(loaded, 0.9),
            "max_checks_at_once": _most_at_once([(start, start + took) for start, took, _ in checks]),
            "max_running_at_once": _most_at_once(_slots(window)),
        },
        "free_disk_min_bytes": min(disk) if disk else None,
    }


def _clip(intervals: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    return [(max(a, start), min(b, end)) for a, b in intervals if min(b, end) > max(a, start)]


def _union(intervals: list[tuple[float, float]]) -> float:
    covered, reach = 0.0, None
    for a, b in sorted(intervals):
        if reach is None or a > reach:
            covered += b - a
            reach = b
        elif b > reach:
            covered += b - reach
            reach = b
    return covered


def window_shares(rows: list[dict[str, Any]], *, start: float, end: float) -> dict[str, Any]:
    """In flight (launch to end), building (launch to last hand-in) and Build-run time, as shares of the window."""
    span = max(1e-9, end - start)
    alive: list[tuple[float, float]] = []
    building: list[tuple[float, float]] = []
    running: list[tuple[float, float]] = []
    for row in _dicts(rows):
        launch = _number(row.get("_launch_epoch"))
        if launch is None:
            continue
        finish = _number(row.get("_end_epoch")) or end
        alive.append((launch, finish))
        handed = [moment for moment in (_number(h.get("submitted_at")) for h in _dicts(row.get("hand_ins"))) if moment]
        building.append((launch, max(handed) if handed else finish))
        for run in _dicts(row.get("runs")):
            began, took = _number(run.get("start")), _seconds(run.get("duration_s"))
            if began is not None and took:
                running.append((began, began + took))
    alive = _clip(alive, start, end)
    return {
        "seconds": round(span, 1),
        "in_flight_avg": round(sum(b - a for a, b in alive) / span, 3),
        "in_flight_max": _most_at_once(alive),
        "building_busy_share": round(_union(_clip(building, start, end)) / span, 3),
        "busy_runs_share": round(_union(_clip(running, start, end)) / span, 3),
    }


def _landings(rows: list[dict[str, Any]]) -> list[float]:
    """The verdict time of every landed hand-in that has one."""
    found = []
    for row in rows:
        for hand_in in _dicts(row.get("hand_ins")):
            moment = _number(hand_in.get("verdict_ts"))
            if hand_in.get("verdict_status") == "landed" and moment is not None:
                found.append(moment)
    return found


def _failures(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """(start, seconds) of every Build run that has a failure class and a measured start and length."""
    found = []
    for row in rows:
        for run in _dicts(row.get("runs")):
            began, took = _number(run.get("start")), _seconds(run.get("duration_s"))
            if run.get("failure_class") and began is not None and took:
                found.append((began, took))
    return found


def per_day(rows: list[dict[str, Any]], *, tz: tzinfo, start: float, end: float) -> list[dict[str, Any]]:
    """Each local day of the window: landings by verdict time, the window shares, and failed-run minutes by start."""
    rows = _dicts(rows)
    landings, failures = _landings(rows), _failures(rows)
    days = []
    cursor = datetime.fromtimestamp(start, tz).replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor.timestamp() < end:
        following = cursor + timedelta(days=1)
        low, high = max(start, cursor.timestamp()), min(end, following.timestamp())
        landed = sum(1 for moment in landings if low <= moment < high)
        failed = sum(took for began, took in failures if low <= began < high)
        shares = window_shares(rows, start=low, end=high)
        days.append(
            {"day": cursor.date().isoformat(), "landed": landed, "failed_run_min": round(failed / 60, 1), **shares}
        )
        cursor = following
    return days


def _line(value: float | None, target: float, met: bool) -> dict[str, Any]:
    return {"value": value, "target": target, "met": None if value is None else met}


def pass_lines(clocks: dict[str, Any], window: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Part 1: the p90 check under load and the disk floor; Part 3: the building share over the whole window."""
    check = clocks.get("check")
    p90 = _measured(check.get("p90_under_load_s")) if isinstance(check, dict) else None
    disk = _measured(clocks.get("free_disk_min_bytes"))
    busy = _measured(window.get("building_busy_share"))
    return {
        "part1_check_p90_s": _line(p90, CHECK_P90_TARGET_S, p90 is not None and p90 <= CHECK_P90_TARGET_S),
        "part1_disk_floor": _line(disk, float(FLOOR_BYTES), disk is not None and disk >= FLOOR_BYTES),
        "part3_build_busy_share": _line(busy, BUSY_TARGET, busy is not None and busy >= BUSY_TARGET),
    }


__all__ = [
    "BUSY_TARGET",
    "CHECK_P90_TARGET_S",
    "CHECK_STAGE",
    "FLOOR_BYTES",
    "PART1_MAX_FILES",
    "SLOT_STAGE",
    "TOGETHER_N",
    "TOGETHER_S",
    "clocks_summary",
    "pass_lines",
    "per_day",
    "window_shares",
]
