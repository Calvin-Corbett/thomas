"""The requirement is re-presented each turn rather than remembered.

`work_onboarding_update` is contracted to be called once per turn before the
model replies, and its receipt is serialized straight into the model's tool
result. Putting the open requirement there means a long conversation cannot erode
it: there is nothing to recall.

The brief informs; it does not enforce. `WorkStore.update_onboarding` owns the
content rules and `onboarding_gate` owns the door.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from thomas.server.work_onboarding_state import validate_work_onboarding_state
from thomas.work.lanes.onboarding_bridge import onboarding_brief


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


def test_an_empty_conversation_is_told_the_goal_is_what_is_open():
    empty = _state(phase="goal_discovery", confirmed_goal="", selected_workflow_id="", selected_workflow_configured=False)
    brief = onboarding_brief(empty, empty)
    assert brief["open_step"] == "goal_discovery"
    assert brief["complete"] is False
    assert any("goal" in requirement for requirement in brief["requirements"])
    assert brief["unmet"], "the model is told what is missing, not just what is required"


def test_a_finished_onboarding_is_told_nothing_is_open():
    brief = onboarding_brief(_state(), _state())
    assert brief["complete"] is True
    assert brief["unmet"] == []


def test_a_self_declared_selection_is_named_in_the_brief():
    browser = _state(selected_workflow_id="", selected_workflow_configured=False)
    brief = onboarding_brief(browser, _state())
    assert brief["open_step"] == "workflow_configuration"
    assert any("recorded user action" in reason for reason in brief["unmet"])


def test_the_brief_does_not_change_between_identical_turns():
    """Regenerated from the lane, so turn fifty reads exactly like turn one."""
    empty = _state(phase="goal_discovery", confirmed_goal="", selected_workflow_id="", selected_workflow_configured=False)
    first = onboarding_brief(empty, empty)
    for _ in range(50):
        assert onboarding_brief(empty, empty) == first


def test_the_chat_route_puts_the_brief_in_the_tool_receipt():
    """A wiring check, not a behaviour one.

    `_work_onboarding_update` is a closure built inside the request handler and
    cannot be called from here, so this asserts the wiring is present rather than
    that it runs. It catches the wire being deleted; it does not prove the model
    sees it. The behaviour above is what proves the brief itself is right.
    """
    source = Path("thomas/server/routes/chat_v2.py").read_text(encoding="utf-8")
    assert "onboarding_brief" in source
    # Computed once, then sent to both readers: the model in the tool receipt and
    # the browser in the emitted event, so the rail and the gates cannot disagree.
    assert "lane_brief = onboarding_brief(work_onboarding_state, state)" in source
    assert '"lane": lane_brief' in source
    assert '"work_onboarding_state", "state": state, "lane": lane_brief' in source
    assert inspect.isfunction(onboarding_brief)
