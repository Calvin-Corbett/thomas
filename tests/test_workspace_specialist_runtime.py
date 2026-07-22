from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.workspace_specialist_test_support import Dispatcher, Tools, operator
from thomas.chat.conversation import ConversationManager
from thomas.core.llm_shared import StreamEvent
from thomas.preferences.store import PreferencesStore
from thomas.server.workspace_specialist_runtime import (
    WORKSPACE_ACTION_POLICIES,
    run_workspace_resident_turn,
    workspace_tool_spec,
)


class _StreamingLLM:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.calls: list[dict[str, Any]] = []

    async def stream_chat(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        for event in self.scripts[len(self.calls) - 1]:
            yield event


def test_every_visible_workspace_has_an_exact_server_owned_action_policy() -> None:
    assert set(WORKSPACE_ACTION_POLICIES) == {
        "mission",
        "office",
        "app_builder",
        "my_stuff",
        "channels",
        "token_economy",
        "marketplace",
        "paper_trading",
        "settings",
    }
    for workspace, policy in WORKSPACE_ACTION_POLICIES.items():
        assert "workspace.inspect" in policy
        assert any(action != "workspace.inspect" for action in policy), workspace
        enum = workspace_tool_spec(workspace)["function"]["parameters"]["properties"]["action"]["enum"]
        assert enum == sorted(policy)
    assert set(WORKSPACE_ACTION_POLICIES["office"]) == {
        "workspace.inspect",
        "mission.jobs.list",
        "office.view.set_follow_agent",
    }
    assert WORKSPACE_ACTION_POLICIES["office"]["office.view.set_follow_agent"].mutating


@pytest.mark.asyncio
async def test_resident_turn_exposes_only_operate_workspace_and_never_dispatches() -> None:
    dispatcher = Dispatcher()
    llm = _StreamingLLM(
        [[StreamEvent(type="token", data={"text": "Mission Control is clear."}), StreamEvent(type="done")]]
    )
    conversation = await run_workspace_resident_turn(
        llm=llm,
        conversation=ConversationManager(),
        prompt="What is happening here?",
        history_prompt="What is happening here?",
        session_id="resident-session",
        operator=operator("mission", dispatcher),
        dispatcher=dispatcher,
        memory_engine=None,
        memory_policy=None,
    )
    offered = llm.calls[0]["tools"]
    assert [tool["function"]["name"] for tool in offered] == ["operate_workspace"]
    system = llm.calls[0]["messages"][0]["content"]
    assert "Never dispatch, delegate, create a task-manager task" in system
    assert "send_task/update_task" in system
    assert conversation.last_assistant_message() == "Mission Control is clear."
    assert not any(
        event["type"].startswith("delegation") or event["type"] == "task_request"
        for event in dispatcher.events
    )
    assert dispatcher.events[-1]["type"] == "done"
    assert dispatcher.events[-1]["specialists_used"] == ["workspace:mission"]


@pytest.mark.asyncio
async def test_resident_tool_call_executes_one_bounded_action_then_summarizes() -> None:
    dispatcher = Dispatcher()
    llm = _StreamingLLM(
        [
            [
                StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "inspect-1",
                        "name": "operate_workspace",
                        "arguments": '{"action":"workspace.inspect"}',
                    },
                ),
                StreamEvent(type="done"),
            ],
            [StreamEvent(type="token", data={"text": "I checked the live workspace state."})],
        ]
    )
    conversation = await run_workspace_resident_turn(
        llm=llm,
        conversation=ConversationManager(),
        prompt="Check it",
        history_prompt="Check it",
        session_id="resident-session",
        operator=operator("mission", dispatcher),
        dispatcher=dispatcher,
        memory_engine=None,
        memory_policy=None,
    )
    assert llm.calls[1]["tools"] is None
    final = conversation.last_assistant_message()
    assert final.startswith("Verified from the server receipt: workspace.inspect succeeded.")
    assert "I checked the live workspace state" not in final
    assert '"workspace": "mission"' in final
    assert any(event["type"] == "tool_result" and event["ok"] for event in dispatcher.events)


@pytest.mark.asyncio
async def test_action_policy_rejects_cross_workspace_capability() -> None:
    dispatcher = Dispatcher()
    receipt = await operator("channels", dispatcher).execute(
        {"action": "preferences.set", "key": "theme", "value": "dark"}
    )
    assert receipt["ok"] is False
    assert receipt["state"] == "rejected"
    assert "outside this workspace allowlist" in receipt["error"]


@pytest.mark.asyncio
async def test_mutation_fails_closed_when_guardrails_are_unavailable(tmp_path: Path) -> None:
    dispatcher = Dispatcher()
    store = PreferencesStore(db_path=str(tmp_path / "prefs.db"))
    receipt = await operator("settings", dispatcher, preferences_store=store).execute(
        {"action": "preferences.set", "key": "ui_density", "value": "dense"}
    )
    assert receipt["ok"] is False
    assert receipt["approval"] == "unavailable"
    assert store.get(user_id="owner-test").advanced.interface.ui_density == "comfortable"


@pytest.mark.asyncio
async def test_preference_lists_are_filtered_to_each_workspace_policy(tmp_path: Path) -> None:
    store = PreferencesStore(db_path=str(tmp_path / "prefs.db"))
    token_receipt = await operator(
        "token_economy", Dispatcher(), preferences_store=store
    ).execute(
        {"action": "preferences.list"}
    )
    settings_receipt = await operator("settings", Dispatcher(), preferences_store=store).execute(
        {"action": "preferences.list"}
    )
    token_preferences = token_receipt["evidence"]["observed"]["preferences"]
    settings_preferences = settings_receipt["evidence"]["observed"]["preferences"]
    assert set(token_preferences) == WORKSPACE_ACTION_POLICIES["token_economy"][
        "preferences.list"
    ].preference_keys
    assert set(settings_preferences) == WORKSPACE_ACTION_POLICIES["settings"][
        "preferences.list"
    ].preference_keys
    assert token_preferences["daily_token_budget"]["path"] == "advanced.cost.daily_token_budget"
    assert settings_preferences["ui_density"]["path"] == "advanced.interface.ui_density"


@pytest.mark.asyncio
async def test_failed_receipt_overrides_a_models_false_success_claim() -> None:
    dispatcher = Dispatcher()
    llm = _StreamingLLM(
        [
            [
                StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "denied-1",
                        "name": "operate_workspace",
                        "arguments": '{"action":"mission.job.cancel","target_id":"job-1"}',
                    },
                )
            ],
            [StreamEvent(type="token", data={"text": "Done, I changed it."})],
        ]
    )
    conversation = await run_workspace_resident_turn(
        llm=llm,
        conversation=ConversationManager(),
        prompt="Cancel it",
        history_prompt="Cancel it",
        session_id="resident-session",
        operator=operator("mission", dispatcher, autonomy_level=1),
        dispatcher=dispatcher,
        memory_engine=None,
        memory_policy=None,
    )
    final = conversation.last_assistant_message()
    assert final.startswith("I did not make that workspace change.")
    assert "Done, I changed it" not in final
    assert not any(event.get("text") == "Done, I changed it." for event in dispatcher.events)


@pytest.mark.asyncio
async def test_success_receipt_overrides_a_models_contradictory_claim() -> None:
    dispatcher = Dispatcher()
    llm = _StreamingLLM(
        [
            [
                StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "inspect-truth-1",
                        "name": "operate_workspace",
                        "arguments": '{"action":"workspace.inspect"}',
                    },
                )
            ],
            [StreamEvent(type="token", data={"text": "I disabled Discord and changed two items."})],
        ]
    )
    conversation = await run_workspace_resident_turn(
        llm=llm,
        conversation=ConversationManager(),
        prompt="Inspect this workspace",
        history_prompt="Inspect this workspace",
        session_id="resident-session",
        operator=operator("mission", dispatcher),
        dispatcher=dispatcher,
        memory_engine=None,
        memory_policy=None,
    )
    final = conversation.last_assistant_message()
    assert final.startswith("Verified from the server receipt: workspace.inspect succeeded.")
    assert "disabled Discord" not in final


@pytest.mark.asyncio
async def test_second_pass_tool_call_is_not_executed() -> None:
    dispatcher = Dispatcher()
    call = StreamEvent(
        type="tool_call_end",
        data={
            "id": "inspect-repeat",
            "name": "operate_workspace",
            "arguments": '{"action":"workspace.inspect"}',
        },
    )
    llm = _StreamingLLM([[call], [call]])
    conversation = await run_workspace_resident_turn(
        llm=llm,
        conversation=ConversationManager(),
        prompt="Inspect once",
        history_prompt="Inspect once",
        session_id="resident-session",
        operator=operator("mission", dispatcher),
        dispatcher=dispatcher,
        memory_engine=None,
        memory_policy=None,
    )
    tool_results = [event for event in dispatcher.events if event["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert conversation.last_assistant_message().startswith("I stopped before a second workspace action")
    assert dispatcher.events[-1]["tool_calls"] == 1
