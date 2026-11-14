"""Where the time went: a summary of the step log (:mod:`thomas.core.step_log`), for deciding what to improve.

Served at ``/api/metrics/steps?days=N`` (``thomas.core.machine_capacity``). Every number is read from the steps
themselves: runs and how they ended, model calls with their tokens, the tools that took the longest, waits for room on
this PC, project starts in their parts, checks, second looks, reloads, and the PC's load while it all happened.
"""

from __future__ import annotations

import collections
import statistics
from typing import Any

TOP_TOOLS = 15
BUSY_PERCENT = 90.0


def _seconds(rows: list[dict[str, Any]], key: str = "seconds") -> list[float]:
    return [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]


def _spread(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "total_s": 0.0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "total_s": round(sum(ordered), 1),
        "median_s": round(statistics.median(ordered), 2),
        "p90_s": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))], 2),
        "max_s": round(ordered[-1], 1),
    }


def _tokens(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The model calls' tokens. ``cached_share`` is over the calls that reported their cache use (rows from
    2026-11-06 on); None when none did, never a 0 that would read as "nothing was cached"."""

    def total(key: str, among: list[dict[str, Any]]) -> int:
        return sum(int(row.get(key) or 0) for row in among)

    reported = [row for row in rows if "cached_prompt_tokens" in row]
    prompt_reported = total("prompt_tokens", reported)
    return {
        "prompt_tokens": total("prompt_tokens", rows),
        "completion_tokens": total("completion_tokens", rows),
        "cached_prompt_tokens": total("cached_prompt_tokens", reported),
        "cache_write_prompt_tokens": total("cache_write_prompt_tokens", reported),
        "cache_reported_calls": len(reported),
        "cached_share": round(total("cached_prompt_tokens", reported) / prompt_reported, 4)
        if prompt_reported
        else None,
    }


def _outcomes(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(collections.Counter(str(row.get("outcome") or "unknown") for row in rows).most_common())


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The step log's rows, summed up by kind of step."""
    by_step: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        by_step[str(row.get("step") or "unknown")].append(row)

    runs, model, tools = by_step.get("run", []), by_step.get("model", []), by_step.get("tool", [])
    per_tool: dict[str, list[float]] = collections.defaultdict(list)
    for row in tools:
        if isinstance(row.get("seconds"), (int, float)):
            per_tool[str(row.get("tool") or "unknown")].append(float(row["seconds"]))
    per_model: dict[str, list[float]] = collections.defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in model:
        by_name[str(row.get("model") or "unknown")].append(row)
        if isinstance(row.get("seconds"), (int, float)):
            per_model[str(row.get("model") or "unknown")].append(float(row["seconds"]))
    waits: dict[str, list[float]] = collections.defaultdict(list)
    for row in by_step.get("load_wait", []):
        waits[str(row.get("where") or "unnamed")].append(float(row.get("seconds") or 0))
    starts = by_step.get("project_start", [])
    loaded = [row for row in rows if isinstance(row.get("cpu"), (int, float))]

    return {
        "steps": len(rows),
        "first_ts": rows[0].get("ts") if rows else None,
        "last_ts": rows[-1].get("ts") if rows else None,
        "by_step": {step: _spread(_seconds(found)) for step, found in sorted(by_step.items())},
        "runs": {**_spread(_seconds(runs)), "by_outcome": _outcomes(runs)},
        "model": {
            **_spread(_seconds(model)),
            **_tokens(model),
            "by_model": {
                name: {**_spread(values), **_tokens(by_name[name])} for name, values in sorted(per_model.items())
            },
        },
        "tools": sorted(
            ({"tool": name, **_spread(values)} for name, values in per_tool.items()),
            key=lambda item: -float(item["total_s"]),
        )[:TOP_TOOLS],
        "load_waits": {where: _spread(values) for where, values in sorted(waits.items())},
        "project_starts": {
            **_spread(_seconds(starts)),
            "copy": _spread(_seconds(starts, "copy_s")),
            "bind": _spread(_seconds(starts, "bind_s")),
            "first_run": _spread(_seconds(starts, "start_s")),
        },
        "checks": {**_spread(_seconds(by_step.get("check", []))), "by_outcome": _outcomes(by_step.get("check", []))},
        "second_looks": {
            **_spread(_seconds(by_step.get("second_look", []))),
            "by_outcome": _outcomes(by_step.get("second_look", [])),
        },
        "reloads": {
            "drains": len(by_step.get("reload_drain", [])),
            "retired": _spread(_seconds(by_step.get("reload_retire", []))),
        },
        "machine": {
            "readings": len(loaded),
            "average_cpu": round(statistics.fmean(float(row["cpu"]) for row in loaded), 1) if loaded else None,
            "share_at_or_over_limit": (
                round(sum(1 for row in loaded if float(row["cpu"]) >= BUSY_PERCENT) / len(loaded), 3)
                if loaded
                else None
            ),
        },
    }


__all__ = ["summarize"]
