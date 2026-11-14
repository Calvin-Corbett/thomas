"""A request that cannot fit stops safely; unrelated builder errors remain visible."""

from __future__ import annotations

import asyncio
import re

import pytest

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig, QualityConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.registry import ToolRegistry


class _RecordingLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(
            name="dummy",
            provider="openai_compat",
            base_url="http://localhost:11434/v1",
            model="dummy-model",
            context_window=2_000,
            max_tokens=256,
        )
        self.calls = 0

    async def stream_chat(self, messages, tools=None, **kwargs):  # noqa: ANN001, ANN003
        self.calls += 1
        yield StreamEvent(type="token", data={"text": "unexpected model call"})
        yield StreamEvent(type="done", data={})


def _agent(llm: _RecordingLLM) -> AgentLoop:
    config = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        quality=QualityConfig(enabled=False, enforce=False),
    )
    return AgentLoop(config, llm, ToolRegistry(), conversation=[], autonomy_level=4)


def _drain(agent: AgentLoop, prompt: str) -> list:
    async def collect() -> list:
        return [event async for event in agent.run(prompt, tools_policy="never", mode="auto")]

    return asyncio.run(collect())


def test_request_too_large_for_window_ends_with_agent_error_and_no_evaluator(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import thomas.agent.acceptance_runtime as acceptance_runtime
    import thomas.agent.loop_completion as loop_completion
    import thomas.agent.loop_execution as loop_execution
    import thomas.agent.loop_turn_context as loop_turn_context
    from thomas.core import acceptance_contract as ac

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "0")
    evaluator_calls = []
    settlements = []
    states = []
    real_build = loop_execution.build_turn_messages
    real_settle = loop_completion.settle_contract

    def contract(loop, *, prompt_text, route_path, attempt=0, workspace=None):  # noqa: ANN001, ANN202, ARG001
        item = ac.ContractItem(item_id="answer", kind="requirement", description="answer the request")
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
        return "ACCEPTANCE CONTRACT: answer the request"

    async def evaluator(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        evaluator_calls.append((args, kwargs))
        raise AssertionError("the evaluator must not run")

    def recording_build(loop, state, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        states.append(state)
        return real_build(loop, state, *args, **kwargs)

    async def recording_settle(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        result = await real_settle(*args, **kwargs)
        settlements.append(result)
        return result

    monkeypatch.setattr(loop_turn_context, "begin_contract", contract)
    monkeypatch.setattr(acceptance_runtime, "evaluate_with_model", evaluator)
    monkeypatch.setattr(loop_execution, "build_turn_messages", recording_build)
    monkeypatch.setattr(loop_completion, "settle_contract", recording_settle)
    llm = _RecordingLLM()
    agent = _agent(llm)

    events = _drain(agent, "feature requirements " * 20_000)

    errors = [event for event in events if event.type == EventType.AGENT_ERROR]
    assert len(errors) == 1
    message = str(errors[0].data)
    assert "instructions and latest user request" in message.lower()
    counts = re.search(r"(\d+) estimated tokens.*?(\d+)-token message budget", message)
    assert counts is not None, message
    assert int(counts.group(1)) > int(counts.group(2)) > 0
    assert llm.calls == 0
    assert not any(event.type == EventType.AGENT_DONE for event in events)
    assert states and states[-1].error and message.find(states[-1].error) >= 0
    assert evaluator_calls == []
    assert settlements and settlements[-1].payload.get("outcome") == "context_budget_exhausted"
    assert settlements[-1].payload.get("evaluated") is False


def test_unrelated_value_error_during_request_build_still_raises(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import thomas.agent.loop_core as loop_core

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "0")
    llm = _RecordingLLM()
    agent = _agent(llm)

    def broken_build(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise ValueError("unrelated request builder bug")

    monkeypatch.setattr(loop_core.AgentLoop, "_build_messages", broken_build)
    with pytest.raises(ValueError, match="unrelated request builder bug"):
        _drain(agent, "hello")
    assert llm.calls == 0


def test_nonpositive_message_budget_reports_both_counts_without_model_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "0")
    llm = _RecordingLLM()
    agent = _agent(llm)
    monkeypatch.setattr(agent, "_request_message_budget", lambda _tools: 0)

    events = _drain(agent, "feature requirements " * 100)

    errors = [event for event in events if event.type == EventType.AGENT_ERROR]
    assert len(errors) == 1
    message = str(errors[0].data)
    counts = re.search(r"(\d+) estimated tokens.*?0-token message budget", message)
    assert counts is not None, message
    assert int(counts.group(1)) > 0
    assert llm.calls == 0
    assert not any(event.type == EventType.AGENT_DONE for event in events)
