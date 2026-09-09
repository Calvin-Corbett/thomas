"""Cross-iteration learning for the evolve loop.

The planner surveys the repo and ranks goals by static leverage, with no memory
of what the loop already tried. That is predictable, but it can re-attempt the
same goal that fails verification every iteration. This module adds a thin,
deterministic memory layer over the loop's persisted history.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .evolve_planner import EvolveGoal

DEFAULT_FAIL_THRESHOLD = 2
_NO_CHANGE_MARKER = "no changes"


@dataclass(frozen=True)
class HistoryStats:
    """Per-goal and per-category tallies distilled from loop history."""

    fails_by_goal: Counter = field(default_factory=Counter)
    fails_by_category: Counter = field(default_factory=Counter)
    promotions_by_category: Counter = field(default_factory=Counter)

    def category_score(self, category: str) -> int:
        """Net category track record: promotions minus real failures."""
        return int(self.promotions_by_category.get(category, 0)) - int(self.fails_by_category.get(category, 0))


def summarize_history(history: list[dict[str, Any]]) -> HistoryStats:
    """Reduce loop history to the tallies the reranker needs."""
    fails_by_goal: Counter = Counter()
    fails_by_category: Counter = Counter()
    promotions_by_category: Counter = Counter()

    for item in history or []:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "")
        goal_id = str(item.get("goal_id") or "")
        decision = item.get("decision") or {}
        action = str(decision.get("action") or "")
        reason = str(decision.get("reason") or "").lower()

        if bool(item.get("promoted")):
            if category:
                promotions_by_category[category] += 1
            continue

        if action == "reject" and _NO_CHANGE_MARKER not in reason:
            if goal_id:
                fails_by_goal[goal_id] += 1
            if category:
                fails_by_category[category] += 1

    return HistoryStats(
        fails_by_goal=fails_by_goal,
        fails_by_category=fails_by_category,
        promotions_by_category=promotions_by_category,
    )


def rerank_by_history(
    goals: list[EvolveGoal],
    history: list[dict[str, Any]],
    *,
    fail_threshold: int = DEFAULT_FAIL_THRESHOLD,
) -> tuple[list[EvolveGoal], list[EvolveGoal]]:
    """Drop repeated-failure tarpits and stably prefer categories that land.

    Returns ``(kept, dropped)``. Dropped goals have failed at least
    ``fail_threshold`` times in this run. Kept goals are stably ordered by
    category score, so the planner's order remains intact within a category.
    """
    stats = summarize_history(history)
    threshold = max(1, int(fail_threshold))

    kept: list[EvolveGoal] = []
    dropped: list[EvolveGoal] = []
    for goal in goals:
        if stats.fails_by_goal.get(goal.id, 0) >= threshold:
            dropped.append(goal)
        else:
            kept.append(goal)

    kept.sort(key=lambda g: stats.category_score(g.category), reverse=True)
    return kept, dropped
