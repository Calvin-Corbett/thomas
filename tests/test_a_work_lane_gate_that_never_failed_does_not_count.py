"""The red-proof rule: a gate is not real until it has been seen failing.

The recurring defect in this repo is a verifier that is broken while the work it
judges is fine. A gate whose failing branch has never executed is a green light
with no bulb, and it is indistinguishable from a working one by its green alone.
So an unproven gate may pass, but its pass does not satisfy the step.
"""

from __future__ import annotations

import pytest

from thomas.work.lanes.gates import GateContext, evaluate_gate
from thomas.work.lanes.model import Gate, Lane, LaneInvalid, Step, validate_lane


def _ctx(**fields):
    return GateContext(fields=fields, artifacts={}, counters={})


def _proof():
    return {"observed_at": "2026-09-08T00:00:00Z", "reason": "goal was empty"}


def test_an_unproven_gate_can_pass_but_its_pass_does_not_count():
    gate = Gate(
        id="goal-substantive",
        kind="mechanical",
        description="the goal is a real sentence",
        check="nonempty_text",
        params={"field": "confirmed_goal", "min_chars": 10},
        red_proof=None,
    )
    verdict = evaluate_gate(gate, _ctx(confirmed_goal="reconcile the daily driver manifests"))
    assert verdict.passed is True, "the predicate itself holds"
    assert verdict.counts is False, "but an unproven gate cannot satisfy a step"
    assert "unproven" in verdict.reason.lower()


def test_the_same_gate_counts_once_it_has_a_recorded_failure():
    gate = Gate(
        id="goal-substantive",
        kind="mechanical",
        description="the goal is a real sentence",
        check="nonempty_text",
        params={"field": "confirmed_goal", "min_chars": 10},
        red_proof=_proof(),
    )
    verdict = evaluate_gate(gate, _ctx(confirmed_goal="reconcile the daily driver manifests"))
    assert verdict.passed is True
    assert verdict.counts is True


def test_a_gate_actually_fails_on_the_input_its_proof_names():
    """The proof is not decoration: the gate must really reject a thin goal."""
    gate = Gate(
        id="goal-substantive",
        kind="mechanical",
        description="the goal is a real sentence",
        check="nonempty_text",
        params={"field": "confirmed_goal", "min_chars": 10},
        red_proof=_proof(),
    )
    verdict = evaluate_gate(gate, _ctx(confirmed_goal="ok"))
    assert verdict.passed is False
    assert verdict.counts is False


def test_a_lane_of_only_judged_gates_is_refused():
    """A lane where every check is a model opinion is theater, not a gate system."""
    lane = Lane(
        id="vibes",
        job_kind="anything",
        version=1,
        steps=[
            Step(
                id="do-it",
                name="Do it",
                gates=[
                    Gate(id="g1", kind="judged", description="is it good?", check="is it good?", params={}),
                    Gate(id="g2", kind="judged", description="is it done?", check="is it done?", params={}),
                ],
            )
        ],
    )
    with pytest.raises(LaneInvalid, match="mechanical or evidence"):
        validate_lane(lane)


def test_a_lane_may_not_grow_past_its_gate_budget_without_approval():
    gates = [
        Gate(
            id=f"g{n}",
            kind="mechanical",
            description="x",
            check="nonempty_text",
            params={"field": "confirmed_goal", "min_chars": 1},
        )
        for n in range(9)
    ]
    lane = Lane(id="fat", job_kind="anything", version=1, steps=[Step(id="s", name="S", gates=gates)])
    with pytest.raises(LaneInvalid, match="budget"):
        validate_lane(lane)


def test_a_threshold_of_zero_means_zero_and_not_the_default():
    """A gate weakened to a zero threshold must visibly weaken, not silently hold.

    `int(params.get(k) or default)` rewrites a configured 0 into the default, so
    a loosened gate keeps behaving strictly and the loosening never surfaces.
    """
    strict = Gate(
        id="len",
        kind="mechanical",
        description="a goal",
        check="nonempty_text",
        params={"field": "confirmed_goal", "min_chars": 0},
        red_proof=_proof(),
    )
    assert evaluate_gate(strict, _ctx(confirmed_goal="")).passed is True, "zero must mean zero"

    defaulted = Gate(
        id="len2",
        kind="mechanical",
        description="a goal",
        check="nonempty_text",
        params={"field": "confirmed_goal"},
        red_proof=_proof(),
    )
    assert evaluate_gate(defaulted, _ctx(confirmed_goal="")).passed is False, "absent still defaults to 1"
