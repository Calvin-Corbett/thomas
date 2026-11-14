"""What one landed change cost, from the step log: Thomas's hours, prompt tokens and cache share, the machine's load.

The 2x goal (2026-11-06) is measured in hours of runs, checks and second looks per change landed on dev; the baseline
that day was 18.4 h and 72M prompt tokens per landing. The speed scoreboard shows this for today and the last 7 days.
Not part of ``thomas.core.step_report``: that module belongs to the machine-capacity row and loads only with it.
"""

from __future__ import annotations

import statistics
from typing import Any

WORK_STEPS = ("run", "check", "second_look")  # the steps whose hours a landed change costs


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def landing_cost(rows: list[dict[str, Any]], landed: int, start: float, end: float) -> dict[str, Any]:
    """The cost of the changes that landed between *start* and *end*, per landing (``None`` when none landed).

    Every run, check and second look in the window counts, the ones that never landed too: they are what a landing
    cost. ``cached_share`` is over the model calls that reported their cache use, ``None`` when none did.
    """
    inside = [row for row in rows if isinstance(row, dict) and start <= float(row.get("ts") or 0) < end]
    hours = sum(
        float(row["seconds"]) for row in inside if row.get("step") in WORK_STEPS and _number(row.get("seconds"))
    )
    model = [row for row in inside if row.get("step") == "model"]
    prompt = sum(int(row.get("prompt_tokens") or 0) for row in model)
    reported = [row for row in model if "cached_prompt_tokens" in row]
    reported_prompt = sum(int(row.get("prompt_tokens") or 0) for row in reported)
    cached = sum(int(row.get("cached_prompt_tokens") or 0) for row in reported)
    cpu = [float(row["cpu"]) for row in inside if _number(row.get("cpu"))]
    memory = [float(row["memory"]) for row in inside if _number(row.get("memory"))]

    def each(total: float) -> float | None:
        return round(total / landed, 2) if landed else None

    return {
        "landed": landed,
        "hours": round(hours / 3600, 2),
        "hours_per_landing": each(hours / 3600),
        "prompt_tokens_per_landing": each(prompt),
        "cached_share": round(cached / reported_prompt, 4) if reported_prompt else None,
        "average_cpu": round(statistics.fmean(cpu), 1) if cpu else None,
        "average_memory": round(statistics.fmean(memory), 1) if memory else None,
    }


__all__ = ["WORK_STEPS", "landing_cost"]
