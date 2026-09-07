"""A connector suggestion the store will refuse never reaches the store (2026-09-06).

Driving Work as a user: "every weekday at 9am check that the verify server
answers, and if not write a note in my Mission Control inbox". Thomas mapped
the job, confirmed the time zone, and enabled "Create job & continue this
flow". The click failed with "connector suggestions are not installed: http
request, mission control inbox". Installed connectors were gmail, google_drive
and google_calendar; the store refuses any other name, and that refusal is
right. The tool schema the model fills in had no description for the field at
all, so it invented two, and the parser passed them through. Now the schema
says what the field is for, and the parser keeps only installed ids, so a
draft can never carry a name the store would refuse.
"""

from __future__ import annotations

from thomas.core.work_onboarding_tool import WORK_ONBOARDING_UPDATE_TOOL
from thomas.server.work_onboarding_state import validate_work_onboarding_state


def _drafts(*suggestions: str) -> list[dict]:
    return [
        {
            "id": "weekday-verify-health-check",
            "name": "Weekday verify-server health check",
            "purpose": "Check the verify server each weekday morning.",
            "type": "scheduled",
            "connector_suggestions": list(suggestions),
        }
    ]


def test_the_schema_tells_the_model_the_field_holds_installed_ids_or_nothing() -> None:
    field = WORK_ONBOARDING_UPDATE_TOOL["function"]["parameters"]["properties"]["workflows"]["items"]["properties"][
        "connector_suggestions"
    ]
    text = str(field.get("description") or "").lower()
    assert "installed" in text and "empty" in text, field


def test_the_parser_keeps_installed_ids_and_drops_the_rest(monkeypatch) -> None:
    monkeypatch.setattr(
        "thomas.server.work_onboarding_state.installed_connector_ids", lambda: frozenset({"gmail", "google_drive"})
    )
    state = validate_work_onboarding_state(
        phase="workflow_mapping",
        confirmed_goal="Check the verify server every weekday at 9am.",
        workflows=_drafts("Gmail", "HTTP request", "Mission Control inbox"),
        selected_workflow_id="",
        selected_workflow_configured=False,
    )
    assert state["workflows"][0]["connector_suggestions"] == ["gmail"]
