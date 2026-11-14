"""The onboarding lane against the defects that are live in the code today.

Two rules exist in `thomas/core/work_onboarding_tool.py` as prose aimed at a
model, with nothing enforcing either: a selection must come from a user click,
and a suggested connector must be installed. The browser appears to verify the
first, but `onboardingConfigurationReady` returns the very field it is checking.

These tests run the lane against the shapes those rules were written to stop.
"""

from __future__ import annotations

import pytest

from thomas.work.lanes.gates import GateContext
from thomas.work.lanes.ledger import RunLedger
from thomas.work.lanes.model import Gate, LaneInvalid, validate_lane
from thomas.work.lanes.onboarding_lane import build_onboarding_lane, onboarding_lane
from thomas.work.lanes.proving import GateCannotFail, prove_gate


def _ledger(level: int = 3) -> RunLedger:
    return RunLedger(lane=onboarding_lane(), autonomy_level=level, run_id="onboard-1")


def _good_goal_ctx() -> GateContext:
    return GateContext(
        fields={"confirmed_goal": "reconcile the daily driver manifests"},
        counters={"user_turns_in_step": 2},
    )


def _good_mapping_ctx() -> GateContext:
    return GateContext(
        fields={"workflows": [{"name": "Daily check", "purpose": "flag missing manifests", "type": "scheduled"}]}
    )


def test_every_gate_in_the_shipped_lane_has_been_seen_failing():
    lane = onboarding_lane()
    for step in lane.steps:
        for gate in step.gates:
            assert gate.proven, f"{gate.id} shipped without a recorded failure"
            assert gate.red_proof["reason"], f"{gate.id} has an empty proof"


def test_a_gate_that_cannot_fail_is_refused_at_build_time():
    """The guard on the guard: a check whose counterexample passes never ships."""
    always_true = Gate(
        id="always-true",
        kind="mechanical",
        description="a goal exists",
        check="nonempty_text",
        params={"field": "confirmed_goal", "min_chars": 1},
        counterexample={"fields": {"confirmed_goal": "this is not actually empty"}},
    )
    with pytest.raises(GateCannotFail, match="passed its own counterexample"):
        prove_gate(always_true)


def test_an_agent_declaring_its_own_selection_does_not_reach_a_created_job():
    """The live defect: the model copies a workflow id it wrote and calls it configured."""
    ledger = _ledger()
    ledger.attempt(_good_goal_ctx())
    ledger.attempt(_good_mapping_ctx())
    assert ledger.open_step().id == "workflow_configuration"

    self_declared = GateContext(
        fields={"selected_workflow_id": "wf-1", "selected_workflow_configured": True},
        provenance={"selected_workflow_id": "model"},
    )
    outcome = ledger.attempt(self_declared)
    assert outcome.advanced is False
    assert "not a recorded user action" in outcome.failures[0]
    assert ledger.completion_verdict().passed is False


def test_the_same_step_passes_once_the_user_has_actually_clicked():
    ledger = _ledger()
    ledger.attempt(_good_goal_ctx())
    ledger.attempt(_good_mapping_ctx())
    clicked = GateContext(
        fields={"selected_workflow_id": "wf-1"},
        provenance={"selected_workflow_id": "user"},
    )
    assert ledger.attempt(clicked).advanced is True
    verdict = ledger.completion_verdict()
    assert verdict.passed is True and verdict.clean is True


def test_a_workflow_missing_its_purpose_does_not_reach_configuration():
    ledger = _ledger()
    ledger.attempt(_good_goal_ctx())
    thin = GateContext(fields={"workflows": [{"name": "Inbox sweep", "type": "event"}]})
    outcome = ledger.attempt(thin)
    assert outcome.advanced is False
    assert any("missing purpose" in f for f in outcome.failures)


def test_an_empty_goal_never_reaches_workflow_mapping():
    ledger = _ledger()
    ledger.attempt(GateContext(fields={"confirmed_goal": ""}, counters={"user_turns_in_step": 0}))
    assert ledger.open_step().id == "goal_discovery"


def test_the_shipped_lane_stays_inside_its_gate_budget():
    validate_lane(build_onboarding_lane())


def test_the_lane_would_be_refused_if_it_grew_past_its_budget():
    lane = build_onboarding_lane()
    lane.steps[0].gates.extend(
        Gate(id=f"extra-{n}", kind="mechanical", description="x", check="nonempty_text", params={})
        for n in range(4)
    )
    with pytest.raises(LaneInvalid, match="budget"):
        validate_lane(lane)
