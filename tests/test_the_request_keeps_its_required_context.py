"""The request builder sends the required context on every build, and never trims out this run's summary."""

from __future__ import annotations

import asyncio

import pytest

from tests.compaction_support import FACT, _build, _group, _group_state, _loop
from thomas.agent.context_compaction import ContextCompactor
from thomas.agent.loop import AgentLoop
from thomas.core.tokens import ContextBudgetExhausted, estimate_messages_tokens

TOOL_FACT = "TOOL-FACT: cobalt-5521"


def test_required_system_text_is_in_the_system_message_of_every_build() -> None:
    task = {"role": "user", "content": "task"}
    agent, _summarizer = _loop([task], window=24000)
    contract = "CONTRACT: result.txt must contain amber-7741"

    first = _build(agent, required_system_text=contract)
    second = _build(agent, memory_text="", required_system_text=contract)

    assert contract in first[0]["content"]
    assert contract in second[0]["content"]


def test_build_refuses_when_required_context_cannot_fit_the_window() -> None:
    agent, _summarizer = _loop([{"role": "user", "content": "task"}], window=2048)

    with pytest.raises(ValueError, match="cannot fit the required instructions"):
        _build(agent, required_system_text="CONTRACT " * 4000)


def test_the_request_budget_is_shared_by_the_hard_cap_and_compaction() -> None:
    agent, _summarizer = _loop([{"role": "user", "content": "task"}], window=24000)
    specs = [{"type": "function", "function": {"name": "big", "description": "d" * 7000, "parameters": {}}}]

    budget = agent._request_message_budget(specs)

    from thomas.core.tokens import estimate_tools_tokens

    expected = 24000 - estimate_tools_tokens(specs) - min(agent.llm.config.max_tokens, 24000 // 4)
    assert budget == expected


class _LongSummarizer:
    """Summarizes faithfully and at length, so the summary itself can be pressured out of a request."""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools=None):  # noqa: ANN001, ANN201
        self.calls += 1
        return {"text": TOOL_FACT + chr(10) + "s" * 6000}


def _summary_then_new_results() -> tuple[AgentLoop, dict]:
    """The task, this run's compaction summary carrying TOOL_FACT, then a newer completed tool exchange."""
    task = {"role": "user", "content": f"Read the files. {FACT}"}
    agent, _summarizer = _loop([task, *_group("q", 10, 5000)], window=24000)
    agent._context_compactor = ContextCompactor(llm=_LongSummarizer(), max_summary_tokens=4000, segment_size=40)
    agent._context_anchors = [task]
    asyncio.run(agent._auto_compact_if_needed(hard_cap=13_000, threshold=0.70, preserve_recent=14))
    summary = next(message for message in agent._conversation if TOOL_FACT in str(message.get("content")))
    agent._conversation.extend(_group("n", 4, 3000))
    return agent, summary


def test_a_current_run_summary_stays_in_the_request_when_it_fits() -> None:
    agent, _summary = _summary_then_new_results()

    wire = _build(agent)

    assert any(TOOL_FACT in str(message.get("content")) for message in wire)
    assert _group_state(wire, "n", 4) == "whole"


def test_a_current_run_summary_is_never_trimmed_out_without_a_stop() -> None:
    agent, summary = _summary_then_new_results()
    full = estimate_messages_tokens(_build(agent))
    summary_tokens = estimate_messages_tokens([summary])
    reserve = min(agent.llm.config.max_tokens, agent._context_window // 4)
    # Room for everything except half the summary: the request builder must drop something.
    agent._context_window = full - summary_tokens // 2 + reserve

    try:
        wire = _build(agent)
    except ContextBudgetExhausted as stop:
        assert "compaction summary" in str(stop), str(stop)
    else:
        assert any(TOOL_FACT in str(message.get("content")) for message in wire), (
            "this run's compaction summary was trimmed out of the request and nothing stopped the run"
        )
