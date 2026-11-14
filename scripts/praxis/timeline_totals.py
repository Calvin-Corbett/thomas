"""Totals per project and across projects, in minutes (``scripts/praxis_timeline.py``). No project is named."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from typing import Any

from scripts.praxis.timeline_phases import OPERATOR_PHASES, OWNER_PHASES, PHASE_ORDER, landed_times, looks


def minutes(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 60.0, 2)


def percentile(values: Iterable[float | None], q: float) -> float | None:
    """The nearest-rank percentile of the values that are not None; None when there are none."""
    kept = sorted(float(value) for value in values if value is not None)
    if not kept:
        return None
    return kept[min(len(kept), max(1, math.ceil(q * len(kept)))) - 1]


def med(values: Iterable[float | None]) -> float | None:
    kept = [float(value) for value in values if value is not None]
    return round(statistics.median(kept), 2) if kept else None


def _rank(phase: str) -> int:
    return PHASE_ORDER.index(phase) if phase in PHASE_ORDER else len(PHASE_ORDER)


def _attempts(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Each settle: from the settling run's end to its second look (or the failed check's repair round)."""
    found: list[dict[str, Any]] = []
    for start, end in looks(row):
        ended = [r["end"] for r in row["runs"] if r["end"] is not None and r["end"] <= start + 0.5]
        settled = max(ended, default=None)
        after = [h for h in row["hand_ins"] if h.get("submitted_at") and 0 <= h["submitted_at"] - end <= 120]
        found.append(
            {
                "at": settled if settled is not None else start,
                "precard_check_min": minutes(start - settled) if settled is not None else None,
                "second_look_min": minutes(end - start),
                "to_submitted_min": minutes(after[0]["submitted_at"] - settled) if after and settled else None,
            }
        )
    for rep in row["repairs"]:
        if rep.get("cause") == "precard_check_failed" and rep.get("at") is not None:
            settled = max(
                (r["end"] for r in row["runs"] if r["end"] is not None and r["end"] <= rep["at"]), default=None
            )
            check = minutes(rep["at"] - settled) if settled is not None else None
            found.append(
                {"at": rep["at"], "precard_check_min": check, "second_look_min": None, "to_submitted_min": None}
            )
    return sorted(found, key=lambda attempt: attempt["at"])


def _hand_in_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for h in row["hand_ins"]:
        submitted, verdict = h.get("submitted_at"), h.get("verdict_ts")
        queued = h["pick"] - submitted if h.get("pick") and submitted else None
        if queued is None and h.get("withdrawn_at") and submitted:
            queued = h["withdrawn_at"] - submitted
        rows.append(
            {
                "verdict": h.get("verdict_status"),
                "queue_behind_other_card_min": minutes(queued),
                "owner_card_min": minutes(h["answered"] - h["card_shown"])
                if h.get("answered") and h.get("card_shown")
                else None,
                "promoter_land_s": round(float(verdict) - h["answered"], 1) if h.get("answered") and verdict else None,
                "submitted_to_verdict_min": minutes(float(verdict) - submitted) if verdict and submitted else None,
                "on_dev": (h.get("commit") or {}).get("on_dev"),
            }
        )
    return rows


def totals(row: dict[str, Any]) -> dict[str, Any]:
    spent = row.get("phases_s") or {}
    launch = row["_launch_epoch"]
    first_run = next((run["start"] for run in row["runs"] if run["start"]), None)
    cards = [h["card_shown"] for h in row["hand_ins"] if h.get("card_shown")]
    submitted = [h["submitted_at"] for h in row["hand_ins"] if h.get("submitted_at")]
    landed = landed_times(row)
    counts: dict[str, int] = {}
    by_kind: dict[str, float] = {}
    not_ok: dict[str, float] = {}
    for run in row["runs"]:
        counts[run["kind"]] = counts.get(run["kind"], 0) + 1
        if run.get("duration_s"):
            by_kind[run["kind"]] = by_kind.get(run["kind"], 0.0) + run["duration_s"] / 60
            if run.get("failure_class"):
                not_ok[run["failure_class"]] = not_ok.get(run["failure_class"], 0.0) + run["duration_s"] / 60
    done = [run for run in row["runs"] if run["kind"] == "done_check" and run["outcome"] != "running"]
    owner = sum(seconds for phase, seconds in spent.items() if phase in OWNER_PHASES)
    operator = sum(seconds for phase, seconds in spent.items() if phase in OPERATOR_PHASES)
    tracked = sum(spent.values())
    attempts = _attempts(row)
    return {
        "launch_to_first_run_min": minutes(first_run - launch) if first_run and launch else None,
        "launch_to_first_hand_in_min": minutes(min(submitted) - launch) if submitted and launch else None,
        "launch_to_first_card_min": minutes(min(cards) - launch) if cards and launch else None,
        "launch_to_landed_min": minutes(max(landed) - launch) if landed and launch else None,
        "tracked_total_min": minutes(tracked),
        "machine_min": minutes(tracked - owner - operator - spent.get("open_now", 0.0)),
        "owner_wait_min": minutes(owner),
        "operator_wait_min": minutes(operator),
        "open_now_min": minutes(spent.get("open_now", 0.0)),
        "run_counts": counts,
        "run_minutes_by_kind": {kind: round(value, 2) for kind, value in by_kind.items()},
        "run_minutes_not_ok": round(sum(not_ok.values()), 2),
        "run_minutes_not_ok_by_class": {name: round(value, 2) for name, value in sorted(not_ok.items())},
        "runs_ok": sum(1 for run in row["runs"] if run.get("ok")),
        "runs_not_ok": sum(1 for run in row["runs"] if run.get("failure_class")),
        "done_checks": len(done),
        "done_checks_changing_files": sum(1 for run in done if (run.get("changed_files") or 0) > 0),
        "repair_rounds": len(row["repairs"]),
        "repair_causes": [rep["cause"] for rep in row["repairs"]],
        "hand_ins": len(row["hand_ins"]),
        "second_looks": len(looks(row)),
        "phase_min": {phase: minutes(spent[phase]) for phase in sorted(spent, key=_rank)},
        "settle_attempts": attempts,
        "check_and_second_look_min_per_hand_in": [a["to_submitted_min"] for a in attempts if a["to_submitted_min"]],
        "hand_in_rows": _hand_in_rows(row),
    }


def _who(phase: str) -> str:
    if phase in OWNER_PHASES:
        return "owner"
    if phase in OPERATOR_PHASES:
        return "operator"
    return "open" if phase == "open_now" else "machine"


def _spread(values: list[float]) -> dict[str, Any]:
    return {"n": len(values), "median_min": med(values), "total_min": round(sum(values), 1),
            "max_min": round(max(values), 1) if values else None}  # fmt: skip


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Across the Thomas-project pipeline's rows: medians, totals, every phase's share, run kinds, checks, cards."""
    scope = [row for row in rows if row["pipeline"] == "thomas_project"]
    if not scope:
        return {"projects": 0, "projects_landed": 0}
    landed = [row for row in scope if row["totals"]["launch_to_landed_min"] is not None]
    every = sorted({phase for row in scope for phase in row["totals"]["phase_min"]}, key=_rank)
    grand = sum(sum((row["totals"]["phase_min"] or {}).values()) for row in scope)
    per_phase = {}
    for phase in every:
        values = [row["totals"]["phase_min"].get(phase, 0.0) or 0.0 for row in scope]
        total = round(sum(values), 1)
        per_phase[phase] = {
            "total_min": total,
            "share_of_all_tracked": round(total / grand, 3) if grand else None,
            "median_min_where_present": med([value for value in values if value > 0]),
            "projects_with_phase": sum(1 for value in values if value > 0),
            "who": _who(phase),
        }
    runs_by_kind: dict[str, list[float]] = {}
    for row in scope:
        for run in row["runs"]:
            if run.get("duration_s"):
                runs_by_kind.setdefault(run["kind"], []).append(run["duration_s"] / 60)
    hand_rows = [hand for row in scope for hand in row["totals"]["hand_in_rows"]]
    attempts = [attempt for row in scope for attempt in row["totals"]["settle_attempts"]]
    machine_phases = {phase: data for phase, data in per_phase.items() if data["who"] == "machine"}
    causes = sorted({rep["cause"] for row in scope for rep in row["repairs"]})
    return {
        "projects": len(scope),
        "projects_landed": len(landed),
        "median_launch_to_first_run_min": med(row["totals"]["launch_to_first_run_min"] for row in scope),
        "median_launch_to_first_hand_in_min": med(row["totals"]["launch_to_first_hand_in_min"] for row in scope),
        "median_launch_to_landed_min": med(row["totals"]["launch_to_landed_min"] for row in landed),
        "median_machine_min_landed_projects": med(row["totals"]["machine_min"] for row in landed),
        "median_owner_wait_min_landed_projects": med(row["totals"]["owner_wait_min"] for row in landed),
        "total_machine_min": round(sum(row["totals"]["machine_min"] or 0 for row in scope), 1),
        "total_owner_wait_min": round(sum(row["totals"]["owner_wait_min"] or 0 for row in scope), 1),
        "total_operator_wait_min": round(sum(row["totals"]["operator_wait_min"] or 0 for row in scope), 1),
        "dominant_phase": max(per_phase, key=lambda phase: per_phase[phase]["total_min"]) if per_phase else None,
        "dominant_machine_phase": max(machine_phases, key=lambda p: machine_phases[p]["total_min"], default=None),
        "per_phase": per_phase,
        "run_kinds": {kind: _spread(values) for kind, values in sorted(runs_by_kind.items())},
        "second_look": _spread([(end - start) / 60 for row in scope for start, end in looks(row)]),
        "precard_check": _spread([a["precard_check_min"] for a in attempts if a["precard_check_min"] is not None]),
        "hand_ins": {
            "count": len(hand_rows),
            "median_owner_card_min": med(hand["owner_card_min"] for hand in hand_rows),
            "median_queue_behind_other_card_min": med(hand["queue_behind_other_card_min"] for hand in hand_rows),
            "median_submitted_to_verdict_min": med(hand["submitted_to_verdict_min"] for hand in hand_rows),
        },
        "runs": {
            "total": sum(len(row["runs"]) for row in scope),
            "ok": sum(row["totals"]["runs_ok"] for row in scope),
            "not_ok": sum(row["totals"]["runs_not_ok"] for row in scope),
            "minutes_not_ok": round(sum(row["totals"]["run_minutes_not_ok"] for row in scope), 1),
        },
        "repair_rounds": sum(row["totals"]["repair_rounds"] for row in scope),
        "repair_causes": {cause: sum(r["totals"]["repair_causes"].count(cause) for r in scope) for cause in causes},
    }


__all__ = ["aggregate", "med", "minutes", "percentile", "totals"]
