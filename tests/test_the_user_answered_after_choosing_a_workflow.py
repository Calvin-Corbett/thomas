"""The engagement rule, rescued from a deletion in progress.

`WorkStore.update_onboarding` carried two bundled rules before launch:

    if user_turns < 4 or thomas_turns < 4:  ...            # conversation length
    if ... user_turns <= selection_turn:    ...            # engagement

The first is being removed and should be: conversation length cannot establish
readiness, and demanding four turns made a simple onboarding unfinishable
(measured 2026-08-05). The second is different in kind. `selected_workflow_user_turn`
is set by the browser to the user-turn count at the moment of the click
(`unified_work_mode.js:516`), so `user_turns > selection_turn` means the user
answered *after* choosing -- they engaged with the configuration rather than the
agent declaring it configured on their behalf.

Only the second is rescued here, and it lives at job creation because that is the
door the run actually uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.work import register_work_routes
from thomas.work import WorkStore
from thomas.work.lanes.gates import GateContext, evaluate_gate
from thomas.work.lanes.model import Gate
from thomas.work.lanes.onboarding_gate import (
    ENGAGEMENT_LANE_ID,
    MINIMAL_LANE_ID,
    creation_decision,
    onboarding_creation_lane,
)


def _gate(**over) -> Gate:
    params = {"field": "user_turns", "marker_field": "selected_workflow_user_turn", "min_marker": 1}
    params.update(over.pop("params", {}))
    return Gate(
        id="answered-after-selection",
        kind="mechanical",
        description="the selection sits at a real user turn",
        check="marker_within_count",
        params=params,
        red_proof={"observed_at": "now", "reason": "seen failing"},
        **over,
    )


def _ctx(user_turns, selection_turn):
    return GateContext(counters={"user_turns": user_turns, "selected_workflow_user_turn": selection_turn})


# ── the check itself ──────────────────────────────────────────────────────────


def test_a_selection_at_an_earlier_turn_passes():
    assert evaluate_gate(_gate(), _ctx(3, 2)).passed is True


def test_choosing_and_configuring_in_one_message_is_allowed():
    """A two-turn onboarding is real; demanding a further turn is what broke it."""
    assert evaluate_gate(_gate(), _ctx(2, 2)).passed is True


def test_a_selection_claimed_at_a_turn_that_never_happened_fails():
    verdict = evaluate_gate(_gate(), _ctx(2, 5))
    assert verdict.passed is False
    assert "beyond" in verdict.reason


def test_a_selection_that_was_never_recorded_fails():
    verdict = evaluate_gate(_gate(), _ctx(5, 0))
    assert verdict.passed is False
    assert "never recorded" in verdict.reason


def test_a_boolean_is_not_a_turn_number():
    """`True` is an int in Python; a gate that accepts it is trivially satisfiable."""
    assert evaluate_gate(_gate(), _ctx(5, True)).passed is False


# ── which lane applies ────────────────────────────────────────────────────────


def _store(tmp_path: Path, *, conversation: bool, user_turns: int = 3, selection_turn: int = 2) -> WorkStore:
    store = WorkStore(tmp_path)
    store.create_app({"id": "ops", "name": "Ops", "goal": "Operate"})
    if conversation:
        for index in range(user_turns):
            store.append_onboarding_message("ops", {"role": "user", "text": f"answer {index}"})
            store.append_onboarding_message("ops", {"role": "thomas", "text": f"follow up {index}"})
        store.update_onboarding(
            "ops",
            {"phase": "workflow_mapping", "fields": {"confirmed_goal": "reconcile the driver manifests"}},
        )
        store.update_onboarding(
            "ops",
            {
                "phase": "workflow_configuration",
                "fields": {
                    "workflow_count": 1,
                    "selected_workflow": "wf-1",
                    "selected_workflow_user_turn": selection_turn,
                },
            },
        )
    return store


def test_an_app_that_was_never_onboarded_runs_the_minimal_lane(tmp_path: Path):
    """Jobs are created directly by missions and tests; that must keep working."""
    store = _store(tmp_path, conversation=False)
    decision = creation_decision(store.get_app("ops")["onboarding"], payload={})
    assert decision.allowed is True
    assert decision.lane_id == MINIMAL_LANE_ID


def test_an_onboarded_app_runs_the_engagement_lane(tmp_path: Path):
    store = _store(tmp_path, conversation=True)
    decision = creation_decision(store.get_app("ops")["onboarding"], payload={})
    assert decision.lane_id == ENGAGEMENT_LANE_ID
    assert decision.allowed is True


def test_an_onboarded_app_whose_selection_turn_never_happened_is_refused(tmp_path: Path):
    store = _store(tmp_path, conversation=True, user_turns=2, selection_turn=9)
    decision = creation_decision(store.get_app("ops")["onboarding"], payload={})
    assert decision.allowed is False
    assert decision.lane_id == ENGAGEMENT_LANE_ID
    assert "selected_workflow_user_turn" in decision.reason


def test_every_pass_says_which_lane_produced_it(tmp_path: Path):
    """A pass whose scope is invisible is how a gate quietly stops guarding."""
    for conversation in (True, False):
        decision = creation_decision(_store(tmp_path / str(conversation), conversation=conversation).get_app("ops")["onboarding"], payload={})
        assert decision.lane_id in {MINIMAL_LANE_ID, ENGAGEMENT_LANE_ID}
        assert decision.lane_id in decision.reason


def test_both_lanes_have_been_seen_failing():
    for lane_id in (MINIMAL_LANE_ID, ENGAGEMENT_LANE_ID):
        lane = onboarding_creation_lane(lane_id)
        gates = [gate for step in lane.steps for gate in step.gates]
        assert gates and all(gate.proven for gate in gates), lane_id


def test_conversation_length_alone_is_not_required(tmp_path: Path):
    """The rules that made a short onboarding unfinishable are NOT rescued.

    Two user turns with the selection on the second: the deleted rule rejected
    this, `finishOnboarding` produces it, and it must be allowed.
    """
    store = _store(tmp_path, conversation=True, user_turns=2, selection_turn=2)
    assert creation_decision(store.get_app("ops")["onboarding"], payload={}).allowed is True


# ── through the route ─────────────────────────────────────────────────────────


async def _client(store: WorkStore) -> TestClient:
    app = web.Application()
    register_work_routes(app, require_api_access=lambda request: None, store=store, mission_canceller=None)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_the_route_refuses_a_selection_the_user_never_made(tmp_path: Path):
    client = await _client(_store(tmp_path, conversation=True, user_turns=2, selection_turn=9))
    try:
        response = await client.post("/api/work/apps/ops/jobs", json={"name": "Declared configured"})
        assert response.status == 409
        assert "selected_workflow_user_turn" in (await response.json())["error"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_the_route_creates_the_job_for_a_real_selection(tmp_path: Path):
    client = await _client(_store(tmp_path, conversation=True, user_turns=3, selection_turn=2))
    try:
        response = await client.post("/api/work/apps/ops/jobs", json={"name": "Engaged"})
        assert response.status == 201
    finally:
        await client.close()
