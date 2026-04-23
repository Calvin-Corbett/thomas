from __future__ import annotations

import pytest

from tests.test_tools_specialist_support import _collect_events, _FakeCodexEvent, _FakeCodexLLM
from thomas.marketplace.specialists.tools import (
    ToolSpecialist,
)


async def test_codex_tools_specialist_suppresses_pretool_narration_for_explicit_tool_requests() -> None:
    llm = _FakeCodexLLM(
        [
            _FakeCodexEvent("token", {"text": "Planning..."})
            ,
            _FakeCodexEvent("tool_call_start", {"name": "write_file", "id": "call-1"}),
            _FakeCodexEvent("tool_call_end", {"name": "write_file", "id": "call-1", "output": "ok"}),
            _FakeCodexEvent("token", {"text": "Done."}),
            _FakeCodexEvent("done"),
        ]
    )
    specialist = ToolSpecialist(config=None, llm=llm, tools=None)

    events = await _collect_events(specialist, "Use your tools to create a file in the current repo.")

    assert llm.seen_messages is not None
    assert any(
        "start with the tool call immediately" in str(message.get("content", "")).lower()
        for message in llm.seen_messages
    )
    assert any(
        "do not list directories" in str(message.get("content", "")).lower()
        for message in llm.seen_messages
    )
    assert any(
        "prefer marketplace skills, plugins, and existing tool context" in str(message.get("content", "")).lower()
        for message in llm.seen_messages
    )
    assert llm.seen_effort == "low"
    assert llm.config.reasoning_effort == "medium"
    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert all("Planning" not in str(event.get("text", "")) for event in events)
    assert events[2]["text"] == "Done."


@pytest.mark.asyncio
async def test_codex_tools_specialist_buffers_text_for_strict_output_only_prompts() -> None:
    llm = _FakeCodexLLM(
        [
            _FakeCodexEvent("token", {"text": "Planning..."})
            ,
            _FakeCodexEvent("tool_call_start", {"name": "run_python", "id": "call-2"}),
            _FakeCodexEvent("tool_call_end", {"name": "run_python", "id": "call-2", "output": "323\r\n"}),
            _FakeCodexEvent("token", {"text": "The script is written. Running it now.323"}),
            _FakeCodexEvent("done"),
        ]
    )
    specialist = ToolSpecialist(config=None, llm=llm, tools=None)

    events = await _collect_events(
        specialist,
        "Use your tools to create calc.py, run it, then answer with only the printed number.",
    )

    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert events[2]["text"] == "323"
    assert events[3]["content"] == "323"


@pytest.mark.asyncio
async def test_codex_tools_specialist_honors_ok_fail_contract_for_strict_output_prompts() -> None:
    llm = _FakeCodexLLM(
        [
            _FakeCodexEvent("tool_call_start", {"name": "schedule_task", "id": "call-reminder"}),
            _FakeCodexEvent(
                "tool_call_end",
                {"name": "schedule_task", "id": "call-reminder", "output": "Thomas Browser 9AM Test Ready"},
            ),
            _FakeCodexEvent("token", {"text": "Thomas Browser 9AM Test Ready"}),
            _FakeCodexEvent("done"),
        ]
    )
    specialist = ToolSpecialist(config=None, llm=llm, tools=None)

    events = await _collect_events(
        specialist,
        "Use your tools to schedule the Thomas Browser 9AM Test reminder. If it works, answer with only OK. If it fails, answer with only FAIL: and the blocker.",
    )

    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert events[2]["text"] == "OK"
    assert events[3]["content"] == "OK"


@pytest.mark.asyncio
async def test_codex_tools_specialist_releases_buffered_text_when_no_tool_call_happens() -> None:
    llm = _FakeCodexLLM(
        [
            _FakeCodexEvent("token", {"text": "No tools needed."}),
            _FakeCodexEvent("done"),
        ]
    )
    specialist = ToolSpecialist(config=None, llm=llm, tools=None)

    events = await _collect_events(specialist, "Use your tools to answer directly if no file change is needed.")

    assert [event["type"] for event in events] == ["text", "done"]
    assert events[0]["text"] == "No tools needed."
    assert events[1]["content"] == "No tools needed."
