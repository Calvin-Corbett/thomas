"""Deterministic completion gating for agent runs.

Completion decisions are derived only from the structured validation report.
Assistant prose is never parsed as a success, failure, retry, or give-up signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GATE_ALLOW = "allow"
GATE_BLOCK = "block"


@dataclass(frozen=True)
class GateDecision:
    """Outcome of the completion gate for one post-loop evaluation."""

    outcome: str
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "reason": self.reason}


def evaluate_completion_gate(
    *,
    validation_passed: bool,
    gate_active: bool,
) -> GateDecision:
    """Allow or block completion from explicit validation state only."""
    if validation_passed:
        return GateDecision(outcome=GATE_ALLOW, reason="validation_passed")
    if not gate_active:
        return GateDecision(outcome=GATE_ALLOW, reason="gate_not_enforced")
    return GateDecision(
        outcome=GATE_BLOCK,
        reason="Required structured validation failed after the configured remediation attempts.",
    )
