"""The run stops rather than continue without its tool results, and a summary carries only what it was given."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.compaction_support import FACT
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig, QualityConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry

TOOL_FACT = "TOOL-FACT: cobalt-5521"


def _drain(events) -> list:  # noqa: ANN001
    async def go():  # noqa: ANN202
        return [event async for event in events]

    return asyncio.run(go())


class _FactReadTool(Tool):
    """Reads ten files; only file_3.txt carries the unique tool fact, on its first line."""

    name = "dummy.read"
    category = "test"
    description = "reads a file"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}

    async def execute(self, args):  # noqa: ANN001, ANN201
        path = str((args or {}).get("path") or "")
        content = f"{TOOL_FACT}\n" + "r" * 4900 if path == "file_3.txt" else "r" * 5000
        return ToolResult(ok=True, data={"content": content})


def _schema_padding_tool(index: int) -> Tool:
    class _SchemaPaddingTool(Tool):
        name = f"dummy.schema{index}"
        category = "test"
        description = "schema padding " * 330
        parameters = {"type": "object", "properties": {}}

        async def execute(self, args):  # noqa: ANN001, ANN201
            _ = args
            return ToolResult(ok=True, data={})

    return _SchemaPaddingTool()


class _TenReadsThenAnswerLLM:
    """The first call reads ten files in one message; later calls answer. Every request is recorded.

    faithful=True makes the summarizer copy the TOOL-FACT line from the text it is given, and nothing else.
    """

    def __init__(self, *, faithful: bool) -> None:
        self.config = ModelConfig(
            name="dummy",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="dummy-model",
            context_window=24_000,
            max_tokens=128,
        )
        self.faithful = faithful
        self.calls = 0
        self.summaries = 0
        self.requests: list[list[dict]] = []

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN201
        self.summaries += 1
        if not self.faithful:
            return {"text": "- earlier reads were summarized"}
        text = " ".join(str(message.get("content")) for message in messages)
        found = [TOOL_FACT] if TOOL_FACT in text else []
        return {"text": "\n".join(found) or "- earlier reads were summarized"}

    async def stream_chat(self, messages, tools=None, **_kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        self.requests.append([dict(message) for message in messages])
        if self.calls == 1:
            for index in range(10):
                call_id = f"read{index}"
                arguments = json.dumps({"path": f"file_{index}.txt"})
                yield StreamEvent(type="tool_call_start", data={"id": call_id, "name": "dummy.read"})
                yield StreamEvent(
                    type="tool_call_end", data={"id": call_id, "name": "dummy.read", "arguments": arguments}
                )
        else:
            yield StreamEvent(type="token", data={"text": "DONE"})
        yield StreamEvent(type="done", data={})


def _ten_reads_loop(llm: _TenReadsThenAnswerLLM) -> AgentLoop:
    config = AppConfig(
        models={"dummy": ModelConfig(name="dummy", model="dummy-model")},
        default_model="dummy",
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_FactReadTool())
    for index in range(7):
        tools.register(_schema_padding_tool(index))
    return AgentLoop(config, llm, tools, conversation=[], autonomy_level=4)


def _request_text(request: list[dict]) -> str:
    return "\n".join(str(message.get("content")) for message in request)


def test_a_fact_from_a_removed_read_reaches_the_continuation_through_a_faithful_summary() -> None:
    llm = _TenReadsThenAnswerLLM(faithful=True)
    agent = _ten_reads_loop(llm)

    _drain(agent.run(f"Read file_0.txt to file_9.txt and report. {FACT}", tools_policy="always", mode="auto"))

    assert len(llm.requests) >= 2, "the run must continue to a second model call"
    second = llm.requests[1]
    assert llm.summaries >= 1, "compaction must summarize before the request builder has to drop results"
    assert TOOL_FACT in _request_text(second), "the continuation lost the fact from the removed read result"
    assert any(message.get("role") == "user" and FACT in str(message.get("content")) for message in second)


def test_a_withheld_fact_does_not_appear_from_nowhere() -> None:
    llm = _TenReadsThenAnswerLLM(faithful=False)
    agent = _ten_reads_loop(llm)

    _drain(agent.run(f"Read file_0.txt to file_9.txt and report. {FACT}", tools_policy="always", mode="auto"))

    assert len(llm.requests) >= 2
    assert TOOL_FACT not in _request_text(llm.requests[1]), (
        "a summary that dropped the fact must not pass as carrying it"
    )


def test_the_run_stops_instead_of_continuing_without_its_tool_results() -> None:
    llm = _TenReadsThenAnswerLLM(faithful=True)
    agent = _ten_reads_loop(llm)
    agent._context_compactor = None

    events = _drain(agent.run(f"Read file_0.txt to file_9.txt and report. {FACT}", tools_policy="always", mode="auto"))

    assert len(llm.requests) == 1, "no further model call may run without this run's tool results"
    errors = [str(event.data) for event in events if event.type == EventType.AGENT_ERROR]
    assert any("dummy.read" in error for error in errors), errors


def test_a_context_budget_stop_makes_no_evaluator_call_and_records_a_recoverable_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # noqa: ANN001
    import thomas.agent.acceptance_runtime as acceptance_runtime
    import thomas.agent.loop_completion as loop_completion
    import thomas.agent.loop_turn_context as loop_turn_context
    from thomas.agent.acceptance_evaluator import EvaluatorResult
    from thomas.core import acceptance_contract as ac

    evaluator_calls: list[dict] = []
    settlements: list = []
    real_settle = loop_completion.settle_contract

    def xhigh_contract(loop, *, prompt_text, route_path, attempt=0, workspace=None):  # noqa: ANN001, ANN202, ARG001
        item = ac.ContractItem(item_id="report", kind="requirement", description="report what the ten reads found")
        loop._acceptance_state = {
            "items": [item],
            "started_at": ac.now(),
            "level": "xhigh",
            "workspace": str(tmp_path),
            "prompt_text": str(prompt_text),
            "first_unmet": None,
            "rounds": 0,
            "effort_original": "xhigh",
        }
        return "ACCEPTANCE CONTRACT: report what the ten reads found"

    async def recording_evaluator(llm, **kwargs):  # noqa: ANN001, ANN003, ANN202
        evaluator_calls.append(dict(kwargs))
        return EvaluatorResult(available=False, items=list(kwargs.get("items") or []), error="recorded")

    async def recording_settle(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        settlement = await real_settle(*args, **kwargs)
        settlements.append(settlement)
        return settlement

    monkeypatch.setattr(loop_turn_context, "begin_contract", xhigh_contract)
    monkeypatch.setattr(acceptance_runtime, "evaluate_with_model", recording_evaluator)
    monkeypatch.setattr(loop_completion, "settle_contract", recording_settle)
    llm = _TenReadsThenAnswerLLM(faithful=True)
    agent = _ten_reads_loop(llm)
    agent._context_compactor = None

    events = _drain(agent.run(f"Read file_0.txt to file_9.txt and report. {FACT}", tools_policy="always", mode="auto"))

    errors = [str(event.data) for event in events if event.type == EventType.AGENT_ERROR]
    assert any("dummy.read" in error for error in errors), errors
    assert len(llm.requests) == 1, "no further worker call may run after a context-budget stop"
    assert llm.summaries == 0
    assert evaluator_calls == [], "the evaluator model ran after a context-budget stop"
    assert [event for event in events if event.type == EventType.AGENT_DONE] == []
    assert settlements, "the contract must still settle, without a model call"
    payload = settlements[-1].payload
    assert payload.get("outcome") == "context_budget_exhausted", payload
    assert payload.get("recoverable") is True
    assert payload.get("evaluated") is False
