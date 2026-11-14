"""A live amendment and an automatic quality repair keep the task, the amendments and the contract."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.compaction_support import AMENDMENT, FACT, _build, _orphans, _ResponsesOwner
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig, QualityConfig
from thomas.core.llm import StreamEvent
from thomas.core.llm_streaming_codex import _build_openai_codex_request
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _PadTool(Tool):
    name = "dummy.pad"
    category = "test"
    description = "always succeeds"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args):  # noqa: ANN001, ANN201
        _ = args
        return ToolResult(ok=True, data={"ok": True})


class _TwoCallsThenAnswerLLM:
    """Odd calls ask for two tool calls in one message; even calls answer. Every request is recorded."""

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
        self.requests: list[list[dict]] = []

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN201
        return {"text": "- earlier steps were summarized"}

    async def stream_chat(self, messages, tools=None, **_kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        self.requests.append([dict(message) for message in messages])
        if self.calls % 2 == 1:
            for suffix in ("a", "b"):
                call_id = f"call{self.calls}{suffix}"
                yield StreamEvent(type="tool_call_start", data={"id": call_id, "name": "dummy.pad"})
                yield StreamEvent(type="tool_call_end", data={"id": call_id, "name": "dummy.pad", "arguments": "{}"})
        else:
            yield StreamEvent(type="token", data={"text": "DONE"})
        yield StreamEvent(type="done", data={})


def _drain(events) -> list:  # noqa: ANN001
    async def go():  # noqa: ANN202
        return [event async for event in events]

    return asyncio.run(go())


def _real_loop(llm: _TwoCallsThenAnswerLLM, queue: asyncio.Queue) -> AgentLoop:
    config = AppConfig(
        models={"dummy": ModelConfig(name="dummy", model="dummy-model")},
        default_model="dummy",
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_PadTool())
    return AgentLoop(config, llm, tools, conversation=[], autonomy_level=4, message_queue=queue)


def test_a_live_amendment_during_a_tool_batch_waits_for_the_whole_exchange() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait(AMENDMENT)
    llm = _TwoCallsThenAnswerLLM()
    agent = _real_loop(llm, queue)

    _drain(agent.run(f"Do the work. {FACT}", tools_policy="always", mode="auto"))

    conversation = agent._conversation
    exchange = next(index for index, message in enumerate(conversation) if message.get("tool_calls"))
    assert [message.get("role") for message in conversation[exchange + 1 : exchange + 4]] == ["tool", "tool", "user"]
    assert conversation[exchange + 3]["content"] == AMENDMENT
    assert any(anchor is conversation[exchange + 3] for anchor in agent._context_anchors)
    second_request = llm.requests[1]
    assert _orphans(second_request) == []
    wire_exchange = next(index for index, message in enumerate(second_request) if message.get("tool_calls"))
    assert [message.get("role") for message in second_request[wire_exchange + 1 : wire_exchange + 3]] == [
        "tool",
        "tool",
    ]
    assert any(message.get("content") == AMENDMENT for message in second_request)


def test_a_quality_retry_keeps_the_task_amendments_and_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    import thomas.agent.loop_execution as loop_execution
    import thomas.agent.loop_turn_context as loop_turn_context

    built: list[tuple[int, str]] = []

    def fake_begin_contract(loop, *, prompt_text, route_path, attempt=0, workspace=None):  # noqa: ANN001, ANN202, ARG001
        # Mirrors the real builder: a remediation pass keeps the contract it was built with and returns no block.
        built.append((attempt, prompt_text))
        return "" if attempt > 0 else f"ACCEPTANCE CONTRACT for: {prompt_text}"

    async def no_hold(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return ""

    monkeypatch.setattr(loop_turn_context, "begin_contract", fake_begin_contract)
    monkeypatch.setattr(loop_execution, "hold_at_finish", no_hold)
    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait(AMENDMENT)
    llm = _TwoCallsThenAnswerLLM()
    agent = _real_loop(llm, queue)
    task_text = f"Do the work. {FACT}"
    remediation = "REMEDIATION: fix the failed checks"

    _drain(agent.run(task_text, tools_policy="always", mode="auto"))
    _drain(agent.run(remediation, tools_policy="always", mode="auto", _quality_retry_count=1))

    contract = f"ACCEPTANCE CONTRACT for: {task_text}"
    assert len(llm.requests) >= 4
    assert all(contract in str(request[0].get("content")) for request in llm.requests), (
        "every call carries the contract"
    )
    assert [text for _attempt, text in built if text != task_text] == [], "the repair built from the remediation text"
    task_message = next(message for message in agent._conversation if message.get("content") == task_text)
    amendment = next(message for message in agent._conversation if message.get("content") == AMENDMENT)
    assert any(anchor is task_message for anchor in agent._context_anchors)
    assert any(anchor is amendment for anchor in agent._context_anchors)

    asyncio.run(agent._auto_compact_if_needed(hard_cap=200, threshold=0.0, preserve_recent=4))
    wire = _build(agent, required_system_text=contract)
    users = [str(message.get("content")) for message in wire if message.get("role") == "user"]
    assert users.index(task_text) < users.index(AMENDMENT)
    assert _orphans(wire) == []
    body = _build_openai_codex_request(_ResponsesOwner(), wire, None, turn_user_content=remediation)
    task_items = [
        item for item in body["input"] if item.get("role") == "user" and FACT in json.dumps(item.get("content"))
    ]
    assert len(task_items) == 1
