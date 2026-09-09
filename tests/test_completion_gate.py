"""Completion decisions use structured validation, never assistant prose."""

import asyncio
import inspect

import pytest

from thomas.agent import completion_gate
from thomas.agent.completion_gate import GATE_ALLOW, GATE_BLOCK, evaluate_completion_gate
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


def test_gate_allows_when_validation_passed() -> None:
    decision = evaluate_completion_gate(validation_passed=True, gate_active=True)
    assert decision.outcome == GATE_ALLOW
    assert decision.reason == "validation_passed"


def test_gate_allows_when_not_enforced() -> None:
    decision = evaluate_completion_gate(validation_passed=False, gate_active=False)
    assert decision.outcome == GATE_ALLOW
    assert decision.reason == "gate_not_enforced"


@pytest.mark.parametrize(
    "assistant_words",
    [
        "Done.",
        "GIVE_UP\nwhat_failed: anything\nwhat_was_tried: everything\nwhy_blocked: reasons",
        "All tests passed and the work is complete.",
        "The task failed and is still broken.",
    ],
)
def test_failed_structured_validation_blocks_regardless_of_assistant_words(assistant_words: str) -> None:
    _ = assistant_words
    decision = evaluate_completion_gate(validation_passed=False, gate_active=True)
    assert decision.outcome == GATE_BLOCK
    assert "structured validation failed" in decision.reason


def test_completion_gate_has_no_prose_input_or_parser() -> None:
    parameters = inspect.signature(evaluate_completion_gate).parameters
    assert set(parameters) == {"validation_passed", "gate_active"}
    assert not hasattr(completion_gate, "parse_give_up")
    source = inspect.getsource(completion_gate)
    assert "import re" not in source
    assert "GIVE_UP_MARKER" not in source


class _WriteTool(Tool):
    name = "diff.create"
    category = "test"
    description = "fake write"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_str": {"type": "string"},
            "new_str": {"type": "string"},
        },
    }

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"path": str(args.get("path", ""))})


class _WriteThenScriptedLLM:
    """First call writes app.py; later calls return scripted texts in order."""

    def __init__(self, texts: list[str]) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._texts = list(texts)
        self._calls = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        self._calls += 1
        if self._calls == 1:
            yield StreamEvent(type="tool_call_start", data={"id": "t1", "name": "diff.create"})
            yield StreamEvent(
                type="tool_call_end",
                data={
                    "id": "t1",
                    "name": "diff.create",
                    "arguments": '{"path":"app.py","old_str":"a","new_str":"b"}',
                },
            )
            yield StreamEvent(type="done", data={})
            return
        text = self._texts.pop(0) if self._texts else "Done."
        yield StreamEvent(type="token", data={"text": text})
        yield StreamEvent(type="done", data={})


def _run_coding(texts: list[str]) -> list:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_WriteTool())
    agent = AgentLoop(cfg, _WriteThenScriptedLLM(texts), tools, conversation=[])

    async def _collect():
        out = []
        async for event in agent.run("fix bug in app.py", tools_policy="always", job_type="coding"):
            out.append(event)
        return out

    return asyncio.run(_collect())


@pytest.mark.parametrize(
    "final_words",
    [
        "Done.",
        (
            "GIVE_UP\n"
            "what_failed: the required coding verification checks never passed\n"
            "what_was_tried: edited app.py and re-ran every required quality check\n"
            "why_blocked: the environment cannot prove the change with verification tooling\n"
        ),
    ],
)
def test_loop_blocks_failed_validation_without_parsing_final_words(final_words: str) -> None:
    events = _run_coding(["Applied the fix.", final_words])
    starts = [event for event in events if event.type == EventType.AGENT_START]
    done = [event for event in events if event.type == EventType.AGENT_DONE]
    errors = [event for event in events if event.type == EventType.AGENT_ERROR]
    assert len(starts) == 2  # initial pass + the configured structured remediation pass
    assert not done
    assert errors
    assert "Completion gate blocked AGENT_DONE" in str(errors[-1].data.get("error") or "")


class _TextOnlyLLM:
    def __init__(self, text: str) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)
        self._text = text

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        yield StreamEvent(type="token", data={"text": self._text})
        yield StreamEvent(type="done", data={})


def test_loop_success_done_has_structured_allow_receipt() -> None:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    agent = AgentLoop(cfg, _TextOnlyLLM("Hi! How can I help?"), ToolRegistry(), conversation=[])

    async def _collect():
        out = []
        async for event in agent.run("hello there", tools_policy="never"):
            out.append(event)
        return out

    events = asyncio.run(_collect())
    done = [event for event in events if event.type == EventType.AGENT_DONE]
    assert len(done) == 1
    gate = (done[-1].data.get("token_report") or {}).get("completion_gate") or {}
    assert gate == {"outcome": GATE_ALLOW, "reason": "validation_passed"}
