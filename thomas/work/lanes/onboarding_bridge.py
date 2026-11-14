"""Turn live Work onboarding state into a gate context, with honest provenance.

Two different values arrive each turn and they do not deserve the same trust:

* ``browser_state`` is what the browser sent -- the selection there was made by
  a person clicking a control; and
* ``model_state`` is what the agent reported about its own work.

The gates that must not accept a self-report read ``provenance``, so this is the
one place that decides which is which. It takes plain dicts and imports nothing
from ``thomas.server``, keeping the lane runtime at the bottom of the tree; the
server does the calling.
"""

from __future__ import annotations

from typing import Any

from .gates import GateContext

USER = "user"
MODEL = "model"


def onboarding_context(
    *,
    browser_state: dict[str, Any] | None,
    model_state: dict[str, Any] | None,
) -> GateContext:
    """Build the context the onboarding lane's gates read."""

    browser = browser_state if isinstance(browser_state, dict) else {}
    model = model_state if isinstance(model_state, dict) else {}

    browser_selection = str(browser.get("selected_workflow_id") or "").strip()
    model_selection = str(model.get("selected_workflow_id") or "").strip()

    # A selection is the user's only when the browser is the one asserting it.
    # An id present only in the model's report is the agent describing its own
    # choice, which is the shape the gate exists to refuse.
    if browser_selection:
        selection, source = browser_selection, USER
    else:
        selection, source = model_selection, MODEL

    workflows = model.get("workflows")
    if not isinstance(workflows, (list, tuple)):
        workflows = browser.get("workflows") if isinstance(browser.get("workflows"), (list, tuple)) else []

    return GateContext(
        fields={
            "phase": str(model.get("phase") or browser.get("phase") or ""),
            "confirmed_goal": str(model.get("confirmed_goal") or browser.get("confirmed_goal") or ""),
            "workflows": list(workflows),
            "selected_workflow_id": selection,
        },
        provenance={"selected_workflow_id": source},
    )


def onboarding_brief(
    browser_state: dict[str, Any] | None,
    model_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """What is still required, restated for the model on this turn.

    This informs; it does not enforce. The onboarding phase machine in
    ``WorkStore.update_onboarding`` owns the content rules and the creation gate
    owns the door. Restating the open requirement every turn is what keeps a long
    conversation from drifting into a rejection it could have avoided.
    """

    from .ledger import RunLedger
    from .onboarding_lane import onboarding_lane

    ledger = RunLedger(lane=onboarding_lane(), autonomy_level=2, run_id="brief", attempts_per_step=99)
    ctx = onboarding_context(browser_state=browser_state, model_state=model_state)
    unmet: list[str] = []
    for _ in range(len(ledger.lane.steps)):
        outcome = ledger.attempt(ctx)
        if not outcome.advanced:
            unmet = list(outcome.failures)
            break

    step = ledger.open_step()
    return {
        "open_step": step.id if step else "",
        "requirements": [gate.description for gate in step.gates] if step else [],
        "unmet": unmet,
        "complete": step is None,
        # The same ledger the gates ran on, shaped for the rail the user sees.
        # Computing it here rather than in the browser keeps one source of truth:
        # a rail derived separately would drift from the gates it depicts, and a
        # rail that disagrees with the gate is worse than no rail.
        "rail": [
            {
                "id": row.id,
                "name": row.name,
                "state": ledger.state_of(row.id),
                "unmet": unmet if step is not None and row.id == step.id else [],
            }
            for row in ledger.lane.steps
        ],
    }
