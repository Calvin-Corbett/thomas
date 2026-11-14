"""The bridge against the real validated shape, not an invented one.

`validate_work_onboarding_state` is what the live route runs on every turn. If
the lane's context builder does not agree with that shape, the lane is only ever
correct about test data.
"""

from __future__ import annotations

from thomas.server.work_onboarding_state import validate_work_onboarding_state
from thomas.work.lanes.ledger import RunLedger
from thomas.work.lanes.onboarding_bridge import onboarding_context
from thomas.work.lanes.onboarding_lane import onboarding_lane


def _state(**over):
    base = {
        "phase": "workflow_configuration",
        "confirmed_goal": "reconcile the daily driver manifests",
        "workflows": [
            {
                "id": "wf-1",
                "name": "Daily check",
                "purpose": "flag missing manifests",
                "type": "scheduled",
                "connector_suggestions": [],
            }
        ],
        "selected_workflow_id": "wf-1",
        "selected_workflow_configured": True,
    }
    base.update(over)
    return validate_work_onboarding_state(**base)


def _run(browser, model):
    ledger = RunLedger(lane=onboarding_lane(), autonomy_level=3, run_id="bridge")
    ctx = onboarding_context(browser_state=browser, model_state=model)
    outcomes = [ledger.attempt(ctx) for _ in range(3)]
    return ledger, outcomes


def test_a_browser_selection_carries_user_provenance():
    ctx = onboarding_context(browser_state=_state(), model_state=_state())
    assert ctx.provenance["selected_workflow_id"] == "user"


def test_a_selection_only_the_model_reports_carries_model_provenance():
    browser = _state(selected_workflow_id="", selected_workflow_configured=False)
    ctx = onboarding_context(browser_state=browser, model_state=_state())
    assert ctx.provenance["selected_workflow_id"] == "model"


def test_a_real_completed_onboarding_passes_every_step():
    ledger, _ = _run(_state(), _state())
    verdict = ledger.completion_verdict()
    assert verdict.passed is True and verdict.clean is True


def test_a_model_only_selection_never_completes_the_lane():
    """The exact shape `selected_workflow_configured: true` cannot rescue."""
    browser = _state(selected_workflow_id="", selected_workflow_configured=False)
    ledger, _ = _run(browser, _state())
    assert ledger.completion_verdict().passed is False
    assert ledger.open_step().id == "workflow_configuration"


def test_the_lane_carries_no_connector_gate_and_no_user_turn_gate():
    """`_installed_only` already drops uninstalled suggestions, on purpose.

    A gate here would be a second source of truth for a rule the server already
    owns, and a stricter one than the server intends -- a suggestion is advice.
    """
    lane = onboarding_lane()
    ids = [gate.id for step in lane.steps for gate in step.gates]
    assert not any("connector" in gate_id for gate_id in ids)
    assert not any(gate_id == "user-answered" for gate_id in ids), "trivially true where it would be checked"
    assert len(ids) == 4
