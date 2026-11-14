"""The Work onboarding lane -- the first job Thomas actually runs.

Onboarding already has three phases, and today the model chooses which one it is
in, writes its own ``confirmed_goal``, and sets ``selected_workflow_configured``
about its own work (``thomas/core/work_onboarding_tool.py``). The rules it is
meant to follow are prose in a tool description:

    "Do not invent a selection; copy selected_workflow_id from the current
     structured state only after the user clicks one."

The browser looks like it re-derives this, but ``onboardingConfigurationReady``
returns ``selected_workflow_configured === true`` -- the claim it was meant to
verify. ``chat_v2`` does refuse a *changed* selection at the tool boundary, and
job creation re-checks none of it.

There is deliberately no "the user answered" gate either. It is trivially true
whenever the update tool runs at all, so its failing case cannot occur at the
point it would be checked -- provably failable, never load-bearing. A gate like
that is theater the fire-rate counter would have retired in twenty runs.

There is deliberately no connector gate here. ``_installed_only`` in
``thomas/server/work_onboarding_state.py`` already drops suggestions for
connectors that are not installed, on the documented grounds that a suggestion is
advice; a gate blocking a step over advice would be a worse rule and a second
source of truth for the same one.
"""

from __future__ import annotations

from .model import Gate, Lane, Step, validate_lane
from .proving import prove_lane

JOB_KIND = "work-onboarding"


def build_onboarding_lane() -> Lane:
    """The lane as authored. Gates are unproven until :func:`prove_lane` runs."""

    return Lane(
        id="work-onboarding",
        job_kind=JOB_KIND,
        version=1,
        steps=[
            Step(
                id="goal_discovery",
                name="Goal",
                gates=[
                    Gate(
                        id="goal-substantive",
                        kind="mechanical",
                        description="the confirmed goal is a real sentence, not a placeholder",
                        check="nonempty_text",
                        params={"field": "confirmed_goal", "min_chars": 12},
                        counterexample={"fields": {"confirmed_goal": ""}},
                    ),
                ],
            ),
            Step(
                id="workflow_mapping",
                name="Workflow map",
                gates=[
                    Gate(
                        id="workflows-mapped",
                        kind="mechanical",
                        description="between one and six workflows are mapped",
                        check="count_between",
                        params={"field": "workflows", "min": 1, "max": 6},
                        counterexample={"fields": {"workflows": []}},
                    ),
                    Gate(
                        id="workflows-purposeful",
                        kind="mechanical",
                        description="every mapped workflow has a name, a purpose and a type",
                        check="each_has",
                        params={"field": "workflows", "keys": ["name", "purpose", "type"]},
                        counterexample={"fields": {"workflows": [{"name": "Daily check"}]}},
                    ),
                ],
            ),
            Step(
                id="workflow_configuration",
                name="Configure one",
                gates=[
                    Gate(
                        id="selection-is-the-users",
                        kind="mechanical",
                        description="the chosen workflow came from a recorded user click, not from the agent",
                        check="user_originated",
                        params={"field": "selected_workflow_id"},
                        counterexample={
                            "fields": {"selected_workflow_id": "wf-1"},
                            "provenance": {"selected_workflow_id": "model"},
                        },
                    ),
                ],
            ),
        ],
    )


def onboarding_lane() -> Lane:
    """The validated, proven lane. Raises if any gate cannot fail."""

    return prove_lane(validate_lane(build_onboarding_lane()))
