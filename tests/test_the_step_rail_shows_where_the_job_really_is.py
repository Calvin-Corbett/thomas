"""The rail reports the ledger, not the model's opinion of its own progress.

The markup it replaces was:

    const phaseIndex = Math.max(0, phases.indexOf(state.onboardingPhase));
    <span class="${phaseIndex >= 0 ? 'is-done' : ''}">1 - Goal</span>

`Math.max` floored the index at 0, so `phaseIndex >= 0` was always true and step
one read as done the moment the wizard opened, before any goal existed. Steps two
and three then lit from `state.onboardingPhase` -- the model's own phase claim.

The rail is computed on the server from the same ledger the gates run on, so the
picture and the enforcement cannot disagree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from thomas.server.work_onboarding_state import validate_work_onboarding_state
from thomas.work.lanes.onboarding_bridge import onboarding_brief

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tests" / "web_node" / "work_step_rail.mjs"
WORK_SUPPORT_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_work_support.js"


def _state(**over):
    base = {
        "phase": "workflow_configuration",
        "confirmed_goal": "reconcile the daily driver manifests",
        "workflows": [
            {"id": "wf-1", "name": "Daily check", "purpose": "flag missing manifests", "type": "scheduled", "connector_suggestions": []}
        ],
        "selected_workflow_id": "wf-1",
        "selected_workflow_configured": True,
    }
    base.update(over)
    return validate_work_onboarding_state(**base)


def _rail(browser, model):
    return {row["id"]: row["state"] for row in onboarding_brief(browser, model)["rail"]}


def test_a_fresh_conversation_shows_no_step_as_done():
    """The whole bug: step one used to read as done before any goal existed."""
    empty = _state(phase="goal_discovery", confirmed_goal="", selected_workflow_id="", selected_workflow_configured=False)
    rail = _rail(empty, empty)
    assert rail["goal_discovery"] == "open"
    assert rail["workflow_mapping"] == "locked"
    assert rail["workflow_configuration"] == "locked"
    assert "passed" not in rail.values()


def test_the_open_step_carries_the_reason_it_is_still_open():
    empty = _state(phase="goal_discovery", confirmed_goal="", selected_workflow_id="", selected_workflow_configured=False)
    rail = onboarding_brief(empty, empty)["rail"]
    assert any("needs at least 12" in reason for reason in rail[0]["unmet"])
    assert rail[1]["unmet"] == [], "a locked step is not blamed for anything"


def test_a_finished_onboarding_shows_every_step_passed():
    rail = _rail(_state(), _state())
    assert set(rail.values()) == {"passed"}


def test_a_self_declared_selection_leaves_the_last_step_open():
    """The rail agrees with the gate: an unconfirmed selection is not progress."""
    browser = _state(selected_workflow_id="", selected_workflow_configured=False)
    rail = _rail(browser, _state())
    assert rail["goal_discovery"] == "passed"
    assert rail["workflow_configuration"] == "open"


def test_the_rail_renders_honestly_in_the_browser() -> None:
    completed = subprocess.run(
        ["node", str(HARNESS), str(WORK_SUPPORT_JS)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"freshWizardShowsNothingDone":true' in completed.stdout
    assert '"waiverIsLoud":true' in completed.stdout
    assert '"blockedIsDistinct":true' in completed.stdout
