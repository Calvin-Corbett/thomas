"""Adversarial review (Step 7) — multiple reviewers grade the deliverable vs the
rubric, each from a distinct lens.

The Exhaustive pipeline's review stage calls ``review_deliverable``. It scores the
work through several lenses (correctness / completeness / robustness), then passes
only when the median score clears the bar AND no reviewer issues a hard veto — so a
single plausible-but-wrong defense can't carry a bad deliverable. It is cost-aware:
when the budget is tight, the reviewer count shrinks (down to a single review)
rather than rejecting the task. The per-lens ``scorer`` is injected so the
aggregation/veto logic is unit-testable; the live wiring supplies reviewer bots.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any

PASS_THRESHOLD = 6.0  # median (out of 10) needed to pass
VETO_THRESHOLD = 3.0  # any reviewer below this hard-vetoes

_LENSES: tuple[str, ...] = ("correctness", "completeness", "robustness")

# scorer signature: (work_result, rubric, lens) -> score in [0, 10]
Scorer = Callable[[Any, dict, str], float]


@dataclass(frozen=True)
class ReviewResult:
    passed: bool
    median_score: float
    scores: tuple[float, ...]
    lenses: tuple[str, ...]
    reviewers: int
    vetoed: bool


def reviewer_count_for(budget_ok: bool) -> int:
    """Full panel when affordable; a single reviewer when the budget is tight."""
    return 3 if budget_ok else 1


def _lenses_for(n: int, lenses: Sequence[str]) -> list[str]:
    base = list(lenses) or list(_LENSES)
    if n <= len(base):
        return base[:n]
    # more reviewers than distinct lenses -> cycle through them
    return [base[i % len(base)] for i in range(n)]


def review_deliverable(
    work_result: Any,
    rubric: dict,
    *,
    scorer: Scorer,
    budget_ok: bool = True,
    lenses: Sequence[str] = _LENSES,
) -> ReviewResult:
    """Score the deliverable through N lenses and decide pass/fail (median + veto)."""
    n = reviewer_count_for(budget_ok)
    used = _lenses_for(n, lenses)
    scores = tuple(max(0.0, min(10.0, float(scorer(work_result, rubric, lens)))) for lens in used)
    med = float(median(scores)) if scores else 0.0
    vetoed = any(s < VETO_THRESHOLD for s in scores)
    passed = bool(scores) and med >= PASS_THRESHOLD and not vetoed
    return ReviewResult(
        passed=passed,
        median_score=med,
        scores=scores,
        lenses=tuple(used),
        reviewers=len(scores),
        vetoed=vetoed,
    )
