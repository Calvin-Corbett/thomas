from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from thomas.core.llm_shared import StreamEvent
from thomas.core.work_onboarding_tool import WORK_ONBOARDING_UPDATE_TOOL
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist
from thomas.server.work_onboarding_state import validate_work_onboarding_state

ROOT = Path(__file__).resolve().parents[1]


def test_structured_work_onboarding_state_validates_without_conversation_text() -> None:
    state = validate_work_onboarding_state(
        phase="workflow_configuration",
        confirmed_goal="Deliver a verified daily owner report.",
        workflows=[
            {
                "id": "owner-report",
                "name": "Owner report",
                "purpose": "Deliver the report every weekday.",
                "type": "scheduled",
                "connector_suggestions": ["gmail"],
            }
        ],
        selected_workflow_id="owner-report",
        selected_workflow_configured=True,
    )

    assert state["selected_workflow_id"] == "owner-report"
    assert state["workflows"][0]["type"] == "scheduled"


def test_structured_work_onboarding_rejects_unbound_selection() -> None:
    with pytest.raises(ValueError, match="must identify a supplied workflow"):
        validate_work_onboarding_state(
            phase="workflow_mapping",
            confirmed_goal="",
            workflows=[],
            selected_workflow_id="invented-by-prose",
            selected_workflow_configured=False,
        )


def test_model_tool_owns_workflow_semantics() -> None:
    function = WORK_ONBOARDING_UPDATE_TOOL["function"]
    assert function["name"] == "work_onboarding_update"
    assert set(function["parameters"]["properties"]["phase"]["enum"]) == {
        "goal_discovery",
        "workflow_mapping",
        "workflow_configuration",
    }
    assert "selected_workflow_id" in function["parameters"]["required"]


@pytest.mark.asyncio
async def test_only_a_structured_model_call_updates_work_onboarding() -> None:
    class Model:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def stream_chat(self, *, messages, tools=None):  # noqa: ANN001, ANN201
            index = len(self.calls)
            self.calls.append({"messages": messages, "tools": tools})

            async def events():
                if index == 0:
                    yield StreamEvent(
                        type="tool_call_end",
                        data={
                            "id": "work-state-1",
                            "name": "work_onboarding_update",
                            "arguments": (
                                '{"phase":"workflow_mapping","confirmed_goal":"Process invoices safely",'
                                '"workflows":[],"selected_workflow_id":"",'
                                '"selected_workflow_configured":false}'
                            ),
                        },
                    )
                else:
                    yield StreamEvent(type="token", data={"text": "Which workflow would you like to configure?"})
                yield StreamEvent(type="done")

            return events()

    updates: list[dict] = []

    async def update(**state):  # noqa: ANN003, ANN202
        updates.append(state)
        return {"ok": True, "state": state}

    model = Model()
    specialist = ReasoningSpecialist(config=None, llm=model)
    token = CapabilityToken(
        specialist_id="reasoning",
        session_id="session",
        allowed_tools=set(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    events = []
    async for event in specialist.execute(
        contract=DelegationContract(
            specialist_id="reasoning",
            input_context={"work_onboarding_update": update},
        ),
        token=token,
        prompt="I need invoice help.",
        conversation_context=[],
        memory_context="",
    ):
        events.append(event)

    assert updates == [
        {
            "phase": "workflow_mapping",
            "confirmed_goal": "Process invoices safely",
            "workflows": [],
            "selected_workflow_id": "",
            "selected_workflow_configured": False,
        }
    ]
    assert {tool["function"]["name"] for tool in model.calls[0]["tools"]} == {"work_onboarding_update"}
    assert model.calls[1]["tools"] is None
    assert any(event.get("type") == "tool_result" and event.get("ok") is True for event in events)


def test_frontend_does_not_classify_onboarding_or_office_priority_from_prose() -> None:
    support = (ROOT / "thomas/server/web/js/unified_work_support.js").read_text(encoding="utf-8")
    office = (ROOT / "thomas/server/web/js/runtime/019_virtual_office_03.js").read_text(encoding="utf-8")

    assert "Workflow:\\s*" not in support
    assert "Goal confirmed:" not in support
    assert "const selectionText" not in support
    assert "const ordinals" not in support
    assert "data-work-select-workflow" in support
    assert "urgencyFromWords" not in office
    assert r"\b(urgent|asap|priority|critical|now)\b" not in office
    assert "structuredPriority" in office


def test_easy_setup_only_accepts_explicit_onboarding_controls() -> None:
    runtime_paths = (
        "thomas/server/web/js/runtime/008_easy_setup_onboarding_06.js",
        "thomas/server/web/js/runtime/011_chat_games_02.js",
        "thomas/server/web/js/modules/007_errormsg.js",
        "thomas/server/web/js/src/runtime_modules/007_errormsg.js",
    )
    sources = {path: (ROOT / path).read_text(encoding="utf-8") for path in runtime_paths}

    forbidden_classifiers = (
        "function includesAny",
        "function isSecurityTrustConcern",
        "function parseOnboardingQuestionAnswer",
        "function parseOnboardingSkipConfirmAction",
        "function parseOnboardingReviewAction",
    )
    for path, source in sources.items():
        for classifier in forbidden_classifiers:
            assert classifier not in source, f"{classifier} must not be live in {path}"

    onboarding = sources["thomas/server/web/js/runtime/008_easy_setup_onboarding_06.js"]
    assert "source: 'explicit_button'" in onboarding
    assert "Onboarding answers only change when you choose one of the visible buttons." in onboarding
    assert "parseOnboardingQuestionAnswer" not in onboarding


def test_office_completion_banter_does_not_classify_task_titles() -> None:
    runtime_paths = ("thomas/server/web/js/runtime/016_session_chat_persistence.js",)
    for path in runtime_paths:
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "taskTitle.includes('benchmark')" not in source
        assert "taskTitle.includes('deploy')" not in source
        assert "if (context === 'task_done')" in source
        assert "return officePick(OFFICE_DIALOGUE.complete);" in source


def test_evolve_actions_are_explicit_only() -> None:
    route = (ROOT / "thomas/server/routes/evolve_loop_routes.py").read_text(encoding="utf-8")
    cli = (ROOT / "thomas/cli/commands/evolve.py").read_text(encoding="utf-8")

    assert not (ROOT / "thomas/forge/anvil/evolve_chat.py").exists()
    assert "/api/evolve/loop/chat" not in route
    assert '@evolve.command("chat")' not in cli
    for explicit_route in (
        "/api/evolve/loop/start",
        "/api/evolve/loop/pause",
        "/api/evolve/loop/approve/{approval_id}",
        "/api/evolve/loop/reject/{approval_id}",
    ):
        assert explicit_route in route
