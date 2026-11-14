"""A real agent loop holds when you pause its Build run, and reads your message as its next turn.

The hook (``agent.run_hold``) is set only by Build; the loop awaits it before each model call and after each tool,
next to the landed-code drain check. The inbox is the loop's ordinary steering queue, file-backed
(thomas/forge/anvil/run_control.py). Chat builds the same AgentLoop and sets neither.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig, QualityConfig
from thomas.core.llm import StreamEvent
from thomas.forge.anvil import run_control
from thomas.forge.anvil.run_control import RunControl
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _PadTool(Tool):
    name = "dummy.pad"
    category = "test"
    description = "always succeeds"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, on_run: Any = None) -> None:
        self.on_run = on_run

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        if self.on_run is not None:
            self.on_run()
        return ToolResult(ok=True, data={"ok": True})


class _ToolThenAnswerLLM:
    """First call asks for one tool; every later call answers. Every request is recorded."""

    def __init__(self) -> None:
        self.config = ModelConfig(
            name="dummy",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="dummy-model",
            context_window=32_000,
            max_tokens=256,
        )
        self.calls = 0
        self.requests: list[list[dict[str, Any]]] = []

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN201
        return {"text": "- summarized"}

    async def stream_chat(self, messages, tools=None, **_kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        self.requests.append([dict(message) for message in messages])
        if self.calls == 1:
            yield StreamEvent(type="tool_call_start", data={"id": "call1", "name": "dummy.pad"})
            yield StreamEvent(type="tool_call_end", data={"id": "call1", "name": "dummy.pad", "arguments": "{}"})
        else:
            yield StreamEvent(type="token", data={"text": "DONE"})
        yield StreamEvent(type="done", data={})


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(run_control, "HOLD_POLL_S", 0.02)


def _loop(llm: _ToolThenAnswerLLM, tool: _PadTool | None = None) -> AgentLoop:
    config = AppConfig(
        models={"dummy": ModelConfig(name="dummy", model="dummy-model")},
        default_model="dummy",
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(tool or _PadTool())
    return AgentLoop(config, llm, tools, conversation=[], autonomy_level=4)


async def _until(condition: Any, seconds: float = 10.0) -> None:
    """Wait for a condition instead of a fixed sleep, so a busy machine cannot make a held run look unheld."""
    deadline = asyncio.get_running_loop().time() + seconds
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "the run never reached its hold"
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.1)  # then a moment in which a run that should be held would show it is not


async def _collect(events: Any) -> list[Any]:
    return [event async for event in events]


def test_a_paused_run_holds_before_its_next_model_call_and_resumes(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    control = RunControl(tmp_path / "run", emit=events.append)
    llm = _ToolThenAnswerLLM()
    agent = _loop(llm)
    agent.run_hold = control.hold
    run_control.set_paused(control.directory, True)

    async def scenario() -> None:
        running = asyncio.create_task(_collect(agent.run("Do the work.", tools_policy="always", mode="auto")))
        await _until(lambda: bool(events))
        assert llm.calls == 0, "a paused run makes no model call"
        assert [event["fc"] for event in events] == ["paused"]
        run_control.set_paused(control.directory, False)
        await asyncio.wait_for(running, 10)

    asyncio.run(scenario())
    assert llm.calls == 2
    assert [event["fc"] for event in events] == ["paused", "resumed"]
    assert events[1]["paused_ms"] > 0  # measured from the moment the loop reached its hold


def test_a_pause_during_a_tool_holds_after_it_before_the_next_model_call(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    control = RunControl(tmp_path / "run", emit=events.append)
    llm = _ToolThenAnswerLLM()
    # You press Pause while the tool is running; the tool still finishes.
    tool = _PadTool(on_run=lambda: run_control.set_paused(control.directory, True))
    agent = _loop(llm, tool)
    agent.run_hold = control.hold

    async def scenario() -> list[Any]:
        running = asyncio.create_task(_collect(agent.run("Do the work.", tools_policy="always", mode="auto")))
        await _until(lambda: bool(events))
        assert llm.calls == 1, "the step in flight finished; the next model call waits"
        assert [event["fc"] for event in events] == ["paused"]
        run_control.set_paused(control.directory, False)
        return await asyncio.wait_for(running, 10)

    loop_events = asyncio.run(scenario())
    assert llm.calls == 2 and [event["fc"] for event in events] == ["paused", "resumed"]
    assert any(getattr(event.type, "value", "") == "tool_result" for event in loop_events)


def test_your_message_to_the_lead_joins_the_run_as_its_next_turn(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    control = RunControl(tmp_path / "run", emit=events.append)
    receipt = run_control.queue_message(control.directory, run_control.LEAD, "make the button blue")
    llm = _ToolThenAnswerLLM()
    agent = _loop(llm)
    agent.run_hold = control.hold
    agent._message_queue = control.inbox(run_control.LEAD)

    asyncio.run(_collect(agent.run("Build the page.", tools_policy="always", mode="auto")))

    assert llm.calls == 2
    assert {"role": "user", "content": "make the button blue"} in llm.requests[1]
    assert events == [{"fc": "steering", "text": "make the button blue", "steer_id": receipt["id"]}]
    [row] = run_control.message_receipts(control.directory, running=True)
    assert row["state"] == "acked" and row["id"] == receipt["id"]


def test_chat_builds_the_same_loop_with_no_hold_and_no_inbox(tmp_path: Path) -> None:
    agent = _loop(_ToolThenAnswerLLM())
    assert getattr(agent, "run_hold", None) is None
    assert agent._message_queue is None
    asyncio.run(_collect(agent.run("Do the work.", tools_policy="always", mode="auto")))
