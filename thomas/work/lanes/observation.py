"""Run one has no gates. It watches, then proposes a lane from what happened.

Gates invented before a job has ever run are guesses, and a wrong gate is the
fastest way to lose trust in the whole mechanism. So the first run of a new job
kind is observed rather than governed: the recorder notes which fields carried
real values as each step closed, and which ones came from the user rather than
from the agent's own report.

What comes out is a *proposal*, never a live lane. Its gates are unproven and it
carries the rationale for each one, so the approval is an informed one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .gates import GateContext
from .model import GATE_BUDGET, Gate, Lane, Step

#: Never propose more than this per step; the lane budget is the harder cap.
MAX_PROPOSED_GATES_PER_STEP = 3


@dataclass
class _Observed:
    step_id: str
    name: str
    text_fields: dict[str, int] = field(default_factory=dict)
    list_fields: dict[str, int] = field(default_factory=dict)
    user_fields: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class LaneProposal:
    lane: Lane
    rationale: list[str]
    needs_approval: bool = True


class ObservationRecorder:
    """Watch one ungated run and turn it into a lane proposal."""

    def __init__(self) -> None:
        self._steps: list[_Observed] = []
        self._index: dict[str, _Observed] = {}

    def observe(self, step_id: str, name: str, ctx: GateContext) -> None:
        seen = self._index.get(step_id)
        if seen is None:
            seen = _Observed(step_id=step_id, name=name)
            self._steps.append(seen)
            self._index[step_id] = seen
        for key, value in ctx.fields.items():
            if isinstance(value, str) and value.strip():
                seen.text_fields[key] = max(seen.text_fields.get(key, 0), len(value.strip()))
            elif isinstance(value, (list, tuple)) and value:
                seen.list_fields[key] = max(seen.list_fields.get(key, 0), len(value))
        for key, source in ctx.provenance.items():
            if str(source).lower() == "user":
                seen.user_fields.add(key)

    def _gates_for(self, seen: _Observed, rationale: list[str]) -> list[Gate]:
        gates: list[Gate] = []

        # A field the user themselves supplied is the strongest thing to protect:
        # it is exactly the value an agent is otherwise free to write for them.
        for name in sorted(seen.user_fields)[:MAX_PROPOSED_GATES_PER_STEP]:
            gates.append(
                Gate(
                    id=f"{seen.step_id}-{name}-from-user",
                    kind="mechanical",
                    description=f"{name} came from the user, not from the agent",
                    check="user_originated",
                    params={"field": name},
                    counterexample={"fields": {name: "x"}, "provenance": {name: "model"}},
                )
            )
            rationale.append(f"{seen.step_id}: {name} was supplied by the user in the observed run")

        for name, count in sorted(seen.list_fields.items()):
            if len(gates) >= MAX_PROPOSED_GATES_PER_STEP:
                break
            gates.append(
                Gate(
                    id=f"{seen.step_id}-{name}-present",
                    kind="mechanical",
                    description=f"{name} has at least one entry",
                    check="count_between",
                    params={"field": name, "min": 1, "max": max(count, 1)},
                    counterexample={"fields": {name: []}},
                )
            )
            rationale.append(f"{seen.step_id}: {name} held {count} entr(y/ies) in the observed run")

        for name, length in sorted(seen.text_fields.items()):
            if len(gates) >= MAX_PROPOSED_GATES_PER_STEP:
                break
            if name in seen.user_fields:
                continue
            floor = max(1, min(length, 12))
            gates.append(
                Gate(
                    id=f"{seen.step_id}-{name}-substantive",
                    kind="mechanical",
                    description=f"{name} is filled in with something substantive",
                    check="nonempty_text",
                    params={"field": name, "min_chars": floor},
                    counterexample={"fields": {name: ""}},
                )
            )
            rationale.append(f"{seen.step_id}: {name} was {length} chars in the observed run")
        return gates

    def propose_lane(self, lane_id: str, job_kind: str) -> LaneProposal:
        rationale: list[str] = []
        steps: list[Step] = []
        budget = GATE_BUDGET
        for seen in self._steps:
            gates = self._gates_for(seen, rationale)[:budget]
            budget -= len(gates)
            steps.append(Step(id=seen.step_id, name=seen.name, gates=gates))
        return LaneProposal(
            lane=Lane(id=lane_id, job_kind=job_kind, version=1, steps=steps),
            rationale=rationale,
        )


def observed_anything(proposal: LaneProposal) -> bool:
    """A proposal with no gates is not worth showing anyone."""

    return any(step.gates for step in proposal.lane.steps)
