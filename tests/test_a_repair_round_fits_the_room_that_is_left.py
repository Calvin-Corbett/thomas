"""A repair turn must fit beside its pinned request, not claim a quarter of the window."""

from __future__ import annotations

import asyncio
import json

from tests.test_a_long_requirement_is_not_sent_twice_to_a_small_window import (
    _done,
    _levels,
    _RecordingLLM,
    _run,
    workspace,  # noqa: F401  -- fixture shared with the other loop regression
)
from tests.test_agent_loop_token_guard import _NoopTool
from thomas.agent.loop import AgentLoop
from thomas.core import acceptance_contract as ac
from thomas.core.acceptance_compact_block import repair_gaps
from thomas.core.config import AppConfig, ModelConfig, QualityConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.core.tokens import estimate_tokens
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


def test_three_hundred_levels_fit_a_repair_round_and_are_judged_whole(workspace) -> None:
    request = _levels(300)
    needs = ac.requirement_statements(request)
    llm = _RecordingLLM(window=8192, effort="xhigh", unmet_rulings=1)

    _done(_run(llm, request))

    assert len(llm.seen) >= 3, "the unmet ruling led to a repair call"
    assert len(llm.judged) >= 2
    for judged in llm.judged[:2]:
        contract = str(judged[1]["content"]).split("CONTRACT (machine verdicts already applied):", 1)[1]
        assert all(f"] {need}" in contract for need in needs), "every ruling sees every need whole"


def test_dropped_earlier_turns_do_not_crowd_out_whole_repair_gaps(workspace) -> None:
    request = " ".join(f"Add widget {n:02d} to the dashboard." for n in range(30))
    needs = ac.requirement_statements(request)

    class ThreeUnmetLLM(_RecordingLLM):
        async def stream_chat(self, messages, tools):  # noqa: ANN001
            self.seen.append([dict(message) for message in messages])
            if len(self.seen) == 1:
                yield StreamEvent(type="tool_call_start", data={"id": "noop_1", "name": "dummy.noop"})
                yield StreamEvent(type="tool_call_end", data={"id": "noop_1", "name": "dummy.noop", "arguments": "{}"})
            else:
                yield StreamEvent(type="token", data={"text": "DONE " + "detail " * 300})
            yield StreamEvent(type="done", data={})

        async def chat(self, messages):  # noqa: ANN001
            self.judged.append([dict(message) for message in messages])
            verdicts = {f"req:{n}": "unmet" if n <= 3 and len(self.judged) == 1 else "met" for n in range(1, 31)}
            reasons = {f"req:{n}": f"widget {n:02d} is missing" for n in range(1, 4)}
            return {
                "text": json.dumps({"item_verdicts": verdicts, "item_reasons": reasons}),
                "tool_calls": [],
                "usage": None,
            }

    llm = ThreeUnmetLLM(window=16384, effort="xhigh")
    config = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=4,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    history = [
        message
        for n in range(600)
        for message in (
            {"role": "user", "content": f"q{n} weather weather weather"},
            {"role": "assistant", "content": f"a{n} sunny sunny sunny"},
        )
    ]
    agent = AgentLoop(config, llm, tools, conversation=history, autonomy_level=4)
    original_history_count = len(history)

    async def collect():
        return [event async for event in agent.run(request, tools_policy="always", max_iterations=4)]

    events = asyncio.run(collect())
    assert not [event for event in events if event.type == EventType.AGENT_ERROR]
    _done(events)
    assert len(llm.seen) >= 3
    assert len(llm.seen[0]) < original_history_count // 2  # most earlier turns were not sent
    assert len(agent._conversation) < original_history_count // 2  # compaction replaced earlier turns
    assert len(llm.seen[2]) < original_history_count // 2  # repair call also drops old turns
    repair = str(llm.seen[2][-1]["content"])
    for n, need in enumerate(needs[:3], 1):
        assert f"- {need} (observed: evaluator: unmet - widget {n:02d} is missing)" in repair
    assert "more requirements" not in repair


def test_compaction_during_run_keeps_tool_evidence_in_repair_call(workspace) -> None:
    class LongResultTool(Tool):
        name = "dummy.long_result"
        category = "test"
        description = "returns a long tool result"
        parameters = {"type": "object", "properties": {}}

        async def execute(self, args):  # noqa: ANN001
            return ToolResult(ok=True, data={"text": "tool evidence " * 550})

    class OneToolThenRepairLLM(_RecordingLLM):
        async def stream_chat(self, messages, tools):  # noqa: ANN001
            self.seen.append([dict(message) for message in messages])
            if len(self.seen) == 1:
                yield StreamEvent(type="tool_call_start", data={"id": "long_1", "name": "dummy.long_result"})
                yield StreamEvent(
                    type="tool_call_end", data={"id": "long_1", "name": "dummy.long_result", "arguments": "{}"}
                )
            else:
                yield StreamEvent(type="token", data={"text": "DONE " + "detail " * 300})
            yield StreamEvent(type="done", data={})

    llm = OneToolThenRepairLLM(window=8192, effort="xhigh", unmet_rulings=1)
    config = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=4,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(LongResultTool())
    history = [
        message
        for n in range(20)
        for message in (
            {"role": "user", "content": f"Earlier question {n}: what happened?"},
            {"role": "assistant", "content": f"Earlier reply {n}: something happened."},
        )
    ]
    original_history_count = len(history)
    agent = AgentLoop(config, llm, tools, conversation=history, autonomy_level=4)

    async def collect():
        return [event async for event in agent.run(_levels(120), tools_policy="always", max_iterations=4)]

    events = asyncio.run(collect())
    assert len(agent._conversation) < original_history_count
    assert any("[context-summary]" in str(message.get("content")) for message in agent._conversation)
    assert not [event for event in events if event.type == EventType.AGENT_ERROR]
    _done(events)
    assert len(llm.seen) >= 3
    assert any(message.get("tool_call_id") == "long_1" for message in llm.seen[2])


def test_no_room_counts_carried_needs_but_returns_uncarried_failures_whole() -> None:
    carried = " ".join(f"Add level {n:03d} to the game." for n in range(60))
    needs = ac.requirement_statements(carried)
    uncarried = "Show the hidden map in the sidebar."
    reason = "the map is not visible"
    items = [
        ac.ContractItem(f"req:{n}", ac.KIND_REQUIREMENT, need, "prompt", need, True, False, "unmet")
        for n, need in enumerate(needs, 1)
    ]
    items.append(ac.ContractItem("goal:1", ac.KIND_REQUIREMENT, uncarried, "goal", uncarried, True, False, reason))

    for budget in (0, -1):
        gaps = repair_gaps(items, [carried], request=carried, budget_tokens=budget)
        assert all(need not in gaps for need in needs)
        assert f"{len(needs)} more requirements" in gaps
        assert f"- {uncarried} (observed: {reason})" in gaps


def test_every_line_of_a_bounded_repair_counts_against_its_budget() -> None:
    request = " ".join(f"Add panel {n:03d} with a map and a toolbar." for n in range(80))
    items = [
        ac.ContractItem(f"req:{n}", ac.KIND_REQUIREMENT, need, "prompt", need, True, False, "unmet")
        for n, need in enumerate(ac.requirement_statements(request), 1)
    ]
    for budget in (1, 12, 40, 80, 160, 320):
        gaps = repair_gaps(items, [request], request=request, budget_tokens=budget)
        assert estimate_tokens(gaps) <= budget, (budget, estimate_tokens(gaps), gaps)
