"""Long-term memory tools match the actual Chat turn policy and engine."""

import copy
import json
from types import SimpleNamespace

import pytest

from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.memory_layers import MemoryContext
from thomas.chat.thinking import ThinkingTracker
from thomas.core.llm_shared import StreamEvent
from thomas.marketplace.orchestrator.brain import OrchestratorBrain
from thomas.marketplace.orchestrator.registry import SpecialistRegistry
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist


class Memory:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.saved = []
        self.retrieved = []

    def add_event(self, **payload):
        if self.fail:
            raise OSError("offline write failure")
        self.saved.append(payload)
        return 1

    def auto_promote_event_memory(self, **_payload):
        pass

    def retrieve(self, **payload):
        self.retrieved.append(payload)
        return SimpleNamespace(text="The remembered color is burnt orange.")


class OfflineModel:
    """Exercise any advertised memory call, then record its real tool receipt."""

    def __init__(self, action="remember"):
        self.action = action
        self.requests = []

    async def stream_chat(self, *, messages, tools=None):
        self.requests.append(copy.deepcopy({"messages": messages, "tools": tools}))
        names = {item["function"]["name"] for item in tools or []}
        if len(self.requests) == 1 and self.action in names:
            args = {"text": "Lantern has four stops at 9:15 AM."} if self.action == "remember" else {"query": "color"}
            yield StreamEvent(
                type="tool_call_end", data={"id": "memory-1", "name": self.action, "arguments": json.dumps(args)}
            )
        else:
            yield StreamEvent(type="token", data={"text": "Lantern: burnt orange, four stops, 9:15 AM."})
        yield StreamEvent(type="done")


class ObservedReasoning(ReasoningSpecialist):
    async def _execute_impl(self, contract, token, prompt, conversation_context, memory_context):
        self.contract = contract
        self.token = token
        async for event in super()._execute_impl(contract, token, prompt, conversation_context, memory_context):
            yield event


async def run_turn(*, engine, enabled=True, scopes=True, action="remember"):
    model = OfflineModel(action)
    specialist = ObservedReasoning(config=None, llm=model, tools=None)
    registry = SpecialistRegistry()
    registry.register(specialist)
    memory_policy = SimpleNamespace(
        enabled=enabled, include_thread=scopes, include_global=scopes, include_profile=scopes
    )
    brain = OrchestratorBrain(
        config=None,
        llm=model,
        memory_engine=engine,
        registry=registry,
        runtime_policy=SimpleNamespace(memory=memory_policy),
    )
    history = [
        {"role": "user", "content": "For this conversation: Lantern is burnt orange, three stops, 8:30 AM."},
        {"role": "assistant", "content": "I have the Lantern details for this conversation."},
    ]
    wire = []

    async def send(data):
        wire.append(json.loads(data))

    result = await brain._dispatch_single(
        session_id="memory-policy-fixture",
        specialist_id="reasoning",
        prompt="Change it to four stops at 9:15 AM. Keep the other details.",
        conversation=ConversationManager(messages=history),
        memory_ctx=MemoryContext(),
        dispatcher=EventDispatcher(send),
        thinking=ThinkingTracker(),
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
        stream_text_events=True,
    )
    assert result.error is None
    return model, specialist, wire, history


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["disabled", "absent", "no-scopes"])
async def test_unavailable_memory_is_not_advertised_but_conversation_context_is_retained(condition):
    engine = None if condition == "absent" else Memory()
    model, specialist, wire, history = await run_turn(
        engine=engine, enabled=condition != "disabled", scopes=condition != "no-scopes"
    )
    request = model.requests[0]
    names = {item["function"]["name"] for item in request["tools"] or []}
    assert not names.intersection({"remember", "recall"})
    assert not specialist.token.allowed_tools.intersection({"remember", "recall"})
    assert specialist.contract.input_context["remember"] is None
    assert specialist.contract.input_context["recall"] is None
    assert len(model.requests) == 1
    assert all(message in request["messages"] for message in history)
    assert "Use the conversation messages already provided" in request["messages"][0]["content"]
    assert "Do not call remember or recall" in request["messages"][0]["content"]
    assert not any(event["type"] == "tool_result" for event in wire)
    if engine is not None:
        assert engine.saved == engine.retrieved == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_enabled_memory_keeps_real_write_receipts_including_failures(fail):
    engine = Memory(fail=fail)
    model, specialist, _wire, _history = await run_turn(engine=engine)
    assert {"remember", "recall"}.issubset(specialist.token.allowed_tools)
    assert len(model.requests) == 2
    receipt = next(message["content"] for message in model.requests[1]["messages"] if message["role"] == "tool")
    if fail:
        assert "NOT saved" in receipt and "couldn't store it" in receipt
        assert engine.saved == []
    else:
        assert receipt.startswith("Saved to your memory:")
        assert engine.saved[0]["text"] == "Lantern has four stops at 9:15 AM."
        assert engine.saved[0]["thread"] == "user_memory"
    assert "Long-term memory is not available for this turn" not in model.requests[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_enabled_recall_returns_actual_memory_evidence():
    engine = Memory()
    model, _specialist, _wire, _history = await run_turn(engine=engine, action="recall")
    receipt = next(message["content"] for message in model.requests[1]["messages"] if message["role"] == "tool")
    assert receipt == "From your memory:\nThe remembered color is burnt orange."
    assert engine.retrieved == [{"query": "color", "thread": "memory-policy-fixture"}]
    assert engine.saved == []
