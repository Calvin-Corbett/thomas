"""Shared fakes for the tests that hold the task, the steering and whole tool groups through every shortening step.

Run 20260912T221756Z-compaction-3a1d59 compacted a worker whose history was the task, one assistant message with
14 tool calls, and their 14 results. compact() cut a raw message count, so it summarized the task together with
the calls and left 14 results whose calls no longer existed. The wire sanitizer then dropped all 14, and the next
request carried the system prompt and a summary: no task.

The tests are split by layer: tests/test_compaction_keeps_the_task.py (compaction),
tests/test_history_trim_keeps_whole_tool_groups.py (heuristic fallback, soft trim, hard cap),
and tests/test_the_request_keeps_its_required_context.py (the request builder).
Agent-loop tests belong to the follow-up change.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from thomas.agent.context_compaction import ContextCompactor
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.llm import TokenUsage
from thomas.tools.registry import ToolRegistry

FACT = "BRIEF-FACT: amber-7741"
AMENDMENT = "AMENDMENT-ONE: also keep notes"


class _LLM:
    def __init__(self, context_window: int) -> None:
        self.config = ModelConfig(
            name="local", provider="openai_compat", model="dummy", context_window=context_window, max_tokens=128
        )
        self.session_usage = TokenUsage()


class _Summarizer:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN201
        self.calls += 1
        return {"text": "- earlier steps were summarized"}


def _call(call_id: str, size: int) -> dict:
    arguments = json.dumps({"path": f"{call_id}.txt", "content": "p" * size})
    return {"id": call_id, "type": "function", "function": {"name": "fs.write_file", "arguments": arguments}}


def _group(prefix: str, count: int, size: int) -> list[dict]:
    calls = [_call(f"{prefix}{index}", size) for index in range(count)]
    results = [{"role": "tool", "tool_call_id": call["id"], "content": f"Wrote {size} chars"} for call in calls]
    return [{"role": "assistant", "content": "", "tool_calls": calls}, *results]


def _orphans(messages: list[dict]) -> list[str]:
    declared: set[str] = set()
    orphans: list[str] = []
    for message in messages:
        declared.update(call["id"] for call in message.get("tool_calls") or [])
        if message.get("role") == "tool" and message.get("tool_call_id") not in declared:
            orphans.append(str(message.get("tool_call_id")))
    return orphans


def _group_state(messages: list[dict], prefix: str, count: int) -> str:
    """Whole when the call and every result are present, absent when none are, otherwise split."""
    ids = {f"{prefix}{index}" for index in range(count)}
    has_call = any(ids & {call["id"] for call in message.get("tool_calls") or []} for message in messages)
    results = {message.get("tool_call_id") for message in messages if message.get("role") == "tool"} & ids
    if has_call and results == ids:
        return "whole"
    if not has_call and not results:
        return "absent"
    return "split"


def _loop(conversation: list[dict], window: int) -> tuple[AgentLoop, _Summarizer]:
    config = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    agent = AgentLoop(config, _LLM(window), ToolRegistry(), conversation=conversation, memory=None)
    summarizer = _Summarizer()
    agent._context_compactor = ContextCompactor(llm=summarizer, max_summary_tokens=400, segment_size=8)
    return agent, summarizer


def _build(agent: AgentLoop, **extra: object) -> list[dict]:
    kwargs: dict[str, object] = {
        "memory_text": "",
        "tool_specs": [],
        "include_purpose": False,
        "include_autonomy_profile": False,
        "include_editing_policy": False,
        "include_project_instructions": False,
        "preserve_first": 2,
        "preserve_last": 12,
    }
    kwargs.update(extra)
    return agent._build_messages(SimpleNamespace(token_estimate=0), **kwargs)


class _ResponsesOwner:
    config = SimpleNamespace(model="gpt-5.6-sol", reasoning_effort="low")

    def _sanitize_tool_name(self, name: str) -> str:
        return name.replace(".", "_")


def _interleaved_history(size: int) -> tuple[list[dict], dict, dict]:
    """The task, one assistant message with two calls, result 0, a live amendment, then result 1."""
    task = {"role": "user", "content": f"Do the work. {FACT}"}
    amendment = {"role": "user", "content": AMENDMENT}
    calls = [_call("i0", size), _call("i1", size)]
    history = [
        task,
        {"role": "assistant", "content": "", "tool_calls": calls},
        {"role": "tool", "tool_call_id": "i0", "content": "done i0"},
        amendment,
        {"role": "tool", "tool_call_id": "i1", "content": "done i1"},
    ]
    return history, task, amendment
