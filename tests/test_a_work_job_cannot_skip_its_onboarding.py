"""A job cannot be created while its onboarding is still collecting.

`update_onboarding` runs a real phase machine: it refuses a phase jump, demands a
twelve-character confirmed goal before mapping, and demands a workflow map and an
explicit selection before configuration. All of it guards a door that job creation
does not use -- measured 2026-09-08, a job was created against an app sitting in
`goal_discovery` with an empty goal.

The rule here is the PHASE, not the state. `finishOnboarding` creates the job
first and builds workflows afterwards, so a job is legitimately created while
onboarding state is still `collecting`; only the phase separates the real finish
from the hole.
"""

from __future__ import annotations

import pytest

from thomas.work import WorkConflictError, WorkStore
from thomas.work.lanes.onboarding_gate import (
    LANE_GATE_FLAG,
    creation_decision,
    onboarding_creation_lane,
)


def _app(tmp_path, *, in_flight: bool) -> WorkStore:
    store = WorkStore(tmp_path)
    store.create_app({"id": "ops", "name": "Ops", "goal": "Operate"})
    if in_flight:
        store.update_onboarding("ops", {"state": "collecting", "phase": "goal_discovery"})
    return store


def test_the_creation_lane_gate_has_been_seen_failing():
    lane = onboarding_creation_lane()
    gates = [gate for step in lane.steps for gate in step.gates]
    assert gates and all(gate.proven for gate in gates)


def test_a_job_is_refused_before_onboarding_reaches_configuration(tmp_path):
    store = _app(tmp_path, in_flight=True)
    decision = creation_decision(store.get_app("ops")["onboarding"], payload={})
    assert decision.allowed is False
    assert "goal_discovery" in decision.reason


def test_a_job_is_allowed_at_configuration_even_though_state_is_still_collecting(tmp_path):
    """The real finish path: the job is created before onboarding is marked ready."""
    store = WorkStore(tmp_path)
    store.create_app({"id": "ops", "name": "Ops", "goal": ""})
    store.update_onboarding(
        "ops", {"phase": "workflow_mapping", "fields": {"confirmed_goal": "reconcile the driver manifests"}}
    )
    store.update_onboarding(
        "ops",
        {"phase": "workflow_configuration", "fields": {"workflow_count": 1, "selected_workflow": "wf-1"}},
    )
    onboarding = store.get_app("ops")["onboarding"]
    assert onboarding["state"] == "collecting", "still collecting, and that is correct here"
    assert creation_decision(onboarding, payload={}).allowed is True


def test_a_finished_onboarding_creates_its_job_as_before(tmp_path):
    store = WorkStore(tmp_path)
    store.create_app({"id": "ops", "name": "Ops", "goal": "Operate"})
    store.update_onboarding(
        "ops",
        {"phase": "workflow_mapping", "fields": {"confirmed_goal": "reconcile the driver manifests"}},
    )
    store.update_onboarding(
        "ops",
        {
            "phase": "workflow_configuration",
            "fields": {"workflow_count": 1, "selected_workflow": "wf-1", "selected_workflow_configured": True},
        },
    )
    store.update_onboarding("ops", {"state": "ready"})
    decision = creation_decision(store.get_app("ops")["onboarding"], payload={})
    assert decision.allowed is True


def test_an_app_that_was_never_onboarded_is_unaffected(tmp_path):
    """Apps are born `ready`; this gate must not change what already works."""
    store = WorkStore(tmp_path)
    store.create_app({"id": "ops", "name": "Ops", "goal": "Operate"})
    assert creation_decision(store.get_app("ops")["onboarding"], payload={}).allowed is True


def test_an_explicit_waiver_creates_the_job_and_records_why(tmp_path):
    """The escape is a recorded human decision, never a silent pass."""
    store = _app(tmp_path, in_flight=True)
    decision = creation_decision(store.get_app("ops")["onboarding"], payload={"waive_lane": True})
    assert decision.allowed is True
    assert decision.waived is True
    assert "goal_discovery" in decision.reason


def test_turning_the_flag_off_restores_the_previous_behaviour(tmp_path, monkeypatch):
    monkeypatch.setenv(LANE_GATE_FLAG, "0")
    store = _app(tmp_path, in_flight=True)
    assert creation_decision(store.get_app("ops")["onboarding"], payload={}).allowed is True


def test_the_refusal_names_the_flag_so_a_wrong_gate_is_never_a_dead_end(tmp_path):
    store = _app(tmp_path, in_flight=True)
    decision = creation_decision(store.get_app("ops")["onboarding"], payload={})
    assert LANE_GATE_FLAG in decision.reason


def test_the_store_still_refuses_a_phase_jump(tmp_path):
    """The phase machine keeps its own rules; this lane adds no second copy."""
    store = _app(tmp_path, in_flight=True)
    with pytest.raises(WorkConflictError):
        store.update_onboarding("ops", {"phase": "workflow_configuration"})
