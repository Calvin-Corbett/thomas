"""Evolve planner -- the autonomous "what should I improve next?" brain.

The refactor pass already auto-targets oversized/stale files. This planner goes
wider: it surveys Thomas across *every* improvement category -- refactor,
reliability, efficiency, security/hardening, tests, features -- and emits a
single ranked backlog of self-chosen goals. Each goal carries a category, a
plain-English rationale, the concrete instruction the evolve engine will run,
the target paths, a risk tier (which feeds the autonomy gate), and a leverage
score (which drives ranking).

This is the piece that turns "a self-improvement tool you aim" into "a system
that decides for itself what to improve". The actual work for each goal is still
done by the existing green-mirror agent pass (`run_evolve_session`); the planner
only *chooses and ranks*. It is deliberately deterministic and cheap so it runs
with no model call and is unit tested against a synthetic project tree.

This module is the public facade: the data model lives in
``evolve_planner_models`` and the detectors in ``evolve_planner_detectors``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .evolve_planner_models import (
    CATEGORIES,
    CATEGORY_RISK,
    FOCUS_ALIASES,
    FOCUS_WEIGHT,
    RISK_ORDER,
    EvolveBacklog,
    EvolveGoal,
    normalize_focus,
    now_iso,
    risk_for_category,
)

__all__ = [
    "CATEGORIES",
    "CATEGORY_RISK",
    "FOCUS_ALIASES",
    "FOCUS_WEIGHT",
    "EvolveBacklog",
    "EvolveGoal",
    "normalize_focus",
    "risk_for_category",
    "plan_backlog",
    "render_backlog_markdown",
    "dumps_backlog",
]

log = logging.getLogger(__name__)


def plan_backlog(
    project_root: Path,
    *,
    focus: str = "",
    categories: set[str] | None = None,
    limit: int = 12,
    ranker: Callable[[list[EvolveGoal], str], list[EvolveGoal]] | None = None,
) -> EvolveBacklog:
    """Survey Thomas and return a ranked backlog of self-chosen improvements.

    Args:
        project_root: repo root to survey.
        focus: free-text focus hint (e.g. "hardening", "perf"); biases ranking.
        categories: allow-list of categories; ``None`` means all of them.
        limit: maximum number of goals to return.
        ranker: optional ``(goals, focus) -> goals`` callable that re-orders the
            deterministic shortlist (e.g. a model-backed impact ranker). The
            planner is deterministic and free by default; injecting a ranker is
            opt-in and the only seam that may incur a model call. Best-effort: a
            failing or empty ranker keeps the deterministic order.
    """
    # Imported lazily so the facade has no import cycle with the detectors
    # (which import the model from this package).
    from .evolve_planner_detectors import collect_candidates

    project_root = Path(project_root)
    focus_category = normalize_focus(focus)
    enabled = {c.lower() for c in categories} if categories else set(CATEGORIES)
    signals: dict[str, Any] = {}

    candidates = [g for g in collect_candidates(project_root, signals) if g.category in enabled]
    candidates.sort(
        key=lambda g: (g.score(focus_category), g.category == focus_category, -RISK_ORDER.get(g.risk_tier, 1)),
        reverse=True,
    )
    if limit > 0:
        candidates = candidates[:limit]

    # Opt-in model-ranking seam (off by default -> deterministic + free). A caller
    # may inject a model-backed ranker to refine the order; it must never break
    # planning, so any failure falls back to the deterministic ranking.
    if ranker is not None:
        try:
            reordered = ranker(list(candidates), focus_category)
        # Best-effort refinement must not break planning -- the deterministic order
        # already stands. ``ranker`` is a caller-injected seam that may reach a model,
        # so this names the transport (OSError), the client/config guards
        # (RuntimeError, ImportError) and the shape faults of an arbitrary callable
        # over the goal objects (AttributeError, IndexError, KeyError, TypeError,
        # ValueError -- the last covering json.JSONDecodeError on a model ranking).
        except (AttributeError, ImportError, IndexError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            log.debug("evolve planner ranker failed; keeping deterministic order: %s", exc)
            reordered = None
        if reordered:
            candidates = list(reordered)

    return EvolveBacklog(
        goals=candidates,
        signals=signals,
        focus=focus_category,
        generated_at=now_iso(),
    )


def render_backlog_markdown(backlog: EvolveBacklog) -> str:
    """Human-readable backlog summary (for the CLI and chat)."""
    lines = ["# Evolve backlog", ""]
    if backlog.focus:
        lines.append(f"Focus: **{backlog.focus}**")
        lines.append("")
    if not backlog.goals:
        lines.append("_No improvements detected right now -- Thomas looks healthy._")
        return "\n".join(lines) + "\n"
    for i, goal in enumerate(backlog.goals, start=1):
        lines.append(f"{i}. [{goal.category}/{goal.risk_tier}] **{goal.title}** (leverage {goal.leverage:.2f})")
        lines.append(f"   - {goal.rationale}")
    return "\n".join(lines) + "\n"


def dumps_backlog(backlog: EvolveBacklog) -> str:
    return json.dumps(backlog.to_dict(), ensure_ascii=False, indent=2)
