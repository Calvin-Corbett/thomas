"""Earn the red proof instead of asserting it.

A gate declares a ``counterexample`` -- a context it claims to reject. Proving
runs the gate against it. If the gate rejects it, the failure is recorded and the
gate becomes proven. If the gate *passes* its own counterexample, that is a gate
which cannot fail, and it is refused here rather than shipped as a green light
with no bulb.

This is deliberately a build-time step, not a runtime one: a lane is proven when
it is created or loaded, so a gate that cannot fail never reaches a real run.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .gates import GateContext, Verdict, evaluate_gate
from .model import Gate, Lane


class GateCannotFail(AssertionError):
    """A gate passed the very input it declared it would reject."""


def _context_from(payload: dict[str, Any]) -> GateContext:
    return GateContext(
        fields=dict(payload.get("fields") or {}),
        artifacts=dict(payload.get("artifacts") or {}),
        counters=dict(payload.get("counters") or {}),
        provenance=dict(payload.get("provenance") or {}),
    )


def prove_gate(gate: Gate, judge: Callable[[str, GateContext], Verdict] | None = None) -> Gate:
    """Stamp ``red_proof`` by observing the gate reject its counterexample."""

    if gate.counterexample is None:
        raise GateCannotFail(
            f"gate {gate.id!r} declares no counterexample, so it can never be proven; "
            "every gate must name an input it rejects"
        )

    # Evaluate the predicate directly: evaluate_gate would report counts=False for
    # an unproven gate, which says nothing about whether the check itself fired.
    verdict = evaluate_gate(gate, _context_from(gate.counterexample), judge)
    if verdict.passed:
        raise GateCannotFail(
            f"gate {gate.id!r} passed its own counterexample ({verdict.reason}); "
            "a gate that cannot fail is not a gate"
        )

    gate.red_proof = {
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": verdict.reason,
        "counterexample": gate.counterexample,
    }
    return gate


def prove_lane(lane: Lane, judge: Callable[[str, GateContext], Verdict] | None = None) -> Lane:
    """Prove every gate in the lane, or raise naming the one that cannot fail."""

    for step in lane.steps:
        for gate in step.gates:
            prove_gate(gate, judge)
    return lane
