"""How much Thomas verifies is the effort slider's decision, not the model's.

One contract, five depths. The slider (``ModelConfig.reasoning_effort``:
none|low|medium|high|xhigh|max, blank = provider default) sets how much of it
runs. ``max`` runs all of it. This module is pure data + pure decisions so the
agent loop wiring stays two lines and the ladder is testable without a model.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

LEVELS = ("none", "low", "medium", "high", "xhigh", "max")
FLAG = "THOMAS_VERIFICATION_CONTRACT"
DEFAULT_LEVEL = "medium"  # a blank slider means the provider default; verify as medium


@dataclass(frozen=True)
class VerificationPlan:
    level: str
    build_acceptance: bool  # write the acceptance list before working
    run_checks: bool  # run the checks in the delivery environment before done
    retry_budget: int  # fix-and-recheck passes when a check fails
    separate_evaluator: bool  # a second model call judges done, not the worker
    evaluator_runs_checks: bool  # the evaluator may execute checks itself
    adversarial: bool  # the evaluator tries to break the deliverable
    learn_from_misses: bool  # a caught miss becomes a permanent check
    reasoning_sandwich: tuple[str, str, str] | None  # plan / build / verify efforts

    def to_payload(self) -> dict[str, object]:
        data = asdict(self)
        data["reasoning_sandwich"] = list(self.reasoning_sandwich) if self.reasoning_sandwich else None
        return data


def normalize_level(effort: str | None) -> str:
    raw = str(effort or "").strip().lower()
    return raw if raw in LEVELS else DEFAULT_LEVEL


def plan_for(effort: str | None) -> VerificationPlan:
    """The ladder. Each level is a superset of the one below it."""

    level = normalize_level(effort)
    rank = LEVELS.index(level)
    return VerificationPlan(
        level=level,
        build_acceptance=rank >= LEVELS.index("low"),
        run_checks=rank >= LEVELS.index("medium"),
        retry_budget={"none": 0, "low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}[level],
        separate_evaluator=rank >= LEVELS.index("xhigh"),
        evaluator_runs_checks=rank >= LEVELS.index("xhigh"),
        adversarial=rank >= LEVELS.index("max"),
        learn_from_misses=rank >= LEVELS.index("max"),
        reasoning_sandwich=("max", "high", "max") if level == "max" else None,
    )


def apply_verification_plan(plan: VerificationPlan, *, quality_max_retries: int, gate_active: bool) -> tuple[int, bool]:
    """Fold the plan into the completion gate's two knobs: how many remediation
    passes are allowed, and whether an unmet validation blocks "done"."""

    retries = max(int(quality_max_retries), plan.retry_budget)
    return retries, bool(gate_active or plan.run_checks)


def verification_contract_enabled() -> bool:
    """On by default; ``THOMAS_VERIFICATION_CONTRACT=0`` restores the old behaviour."""

    from thomas.core.acceptance_contract import contract_enabled

    return contract_enabled()
