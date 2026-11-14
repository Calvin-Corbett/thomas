"""Lane, step, and gate shapes, plus the rules a lane must satisfy to exist.

Two rules are enforced here rather than left to good intentions:

* a lane needs at least one mechanical or evidence gate, because a lane whose
  every check is a model opinion cannot block anything; and
* a lane has a gate budget, because evolution that only ever adds ends in a job
  that spends its whole budget on ceremony.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GATE_KINDS = ("mechanical", "evidence", "judged")

#: Gates per lane before growth itself needs approval.
GATE_BUDGET = 7


class LaneInvalid(ValueError):
    """A lane definition that must not be created or loaded."""


@dataclass
class Gate:
    """One check standing between a step and the next one.

    ``counterexample`` is a context this gate is asserted to reject, and
    ``red_proof`` is the recorded observation of it actually doing so. Until the
    proof is stamped the gate is unproven and its pass does not satisfy a step --
    a gate whose failing branch has never run is indistinguishable from a broken
    one. See :mod:`thomas.work.lanes.proving`.
    """

    id: str
    kind: str
    description: str
    check: str
    params: dict[str, Any] = field(default_factory=dict)
    counterexample: dict[str, Any] | None = None
    red_proof: dict[str, Any] | None = None
    checked_count: int = 0
    fired_count: int = 0

    @property
    def proven(self) -> bool:
        return isinstance(self.red_proof, dict) and bool(self.red_proof)


@dataclass
class Step:
    id: str
    name: str
    gates: list[Gate] = field(default_factory=list)


@dataclass
class Lane:
    id: str
    job_kind: str
    version: int
    steps: list[Step] = field(default_factory=list)


def _all_gates(lane: Lane) -> list[Gate]:
    return [gate for step in lane.steps for gate in step.gates]


def validate_lane(lane: Lane) -> Lane:
    """Return the lane, or raise :class:`LaneInvalid` naming the broken rule."""

    if not lane.steps:
        raise LaneInvalid("a lane needs at least one step")

    seen_steps: set[str] = set()
    seen_gates: set[str] = set()
    for step in lane.steps:
        if step.id in seen_steps:
            raise LaneInvalid(f"duplicate step id: {step.id}")
        seen_steps.add(step.id)
        for gate in step.gates:
            if gate.kind not in GATE_KINDS:
                raise LaneInvalid(f"unknown gate kind: {gate.kind}")
            if gate.id in seen_gates:
                raise LaneInvalid(f"duplicate gate id: {gate.id}")
            seen_gates.add(gate.id)

    gates = _all_gates(lane)
    if not any(gate.kind in ("mechanical", "evidence") for gate in gates):
        raise LaneInvalid(
            "a lane needs at least one mechanical or evidence gate; "
            "a lane judged only by a model cannot block anything"
        )
    if len(gates) > GATE_BUDGET:
        raise LaneInvalid(
            f"lane has {len(gates)} gates, over the budget of {GATE_BUDGET}; "
            "growing the budget is itself a proposal"
        )
    return lane
