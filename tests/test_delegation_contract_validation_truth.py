"""Delegation results are completed only after a real output contract passes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from thomas.chat.conversation import ConversationManager
from thomas.chat.memory_layers import MemoryContext
from thomas.marketplace.orchestrator.brain import OrchestratorBrain
from thomas.marketplace.orchestrator.protocol import DelegationContract, SpecialistStatus


class _EmptySpecialist:
    capabilities = {"reasoning"}

    async def execute(self, **_kwargs: Any):
        yield {"type": "done", "iterations": 1}


class _Registry:
    def __init__(self) -> None:
        self.specialist = _EmptySpecialist()
        self.executed: list[str] = []

    def get(self, specialist_id: str) -> _EmptySpecialist | None:
        return self.specialist if specialist_id == "reasoning" else None

    def record_execution(self, specialist_id: str) -> None:
        self.executed.append(specialist_id)


class _Dispatcher:
    def __init__(self) -> None:
        self.activity: list[dict[str, Any]] = []

    async def emit_delegation(self, **_payload: Any) -> None:
        return None

    async def emit_agent_activity(self, **payload: Any) -> None:
        self.activity.append(payload)

    async def emit(self, _payload: dict[str, Any]) -> None:
        return None


def test_default_contract_requires_meaningful_content() -> None:
    contract = DelegationContract(specialist_id="reasoning")

    assert contract.success_criteria == {"required_fields": ["content"], "min_content_length": 1}
    assert contract.validate_output({"content": "answer"}) is True
    assert contract.validate_output({}) is False
    assert contract.validate_output({"content": ""}) is False
    assert contract.validate_output({"content": "   \t"}) is False
    assert contract.validate_output({"content": 1}) is False


def test_contract_criteria_are_fresh_and_fail_closed_when_malformed() -> None:
    first = DelegationContract()
    second = DelegationContract()
    first.success_criteria["required_fields"].append("evidence")

    assert second.success_criteria["required_fields"] == ["content"]
    assert DelegationContract(success_criteria={}).validate_output({"content": "answer"}) is False
    assert DelegationContract(success_criteria={"required_fields": []}).validate_output({"content": "answer"}) is False
    assert (
        DelegationContract(success_criteria={"min_content_length": 0}).validate_output({"content": "answer"}) is False
    )
    assert DelegationContract(success_criteria={"unknown": True}).validate_output({"content": "answer"}) is False
    assert (
        DelegationContract(success_criteria={"required_fields": "content"}).validate_output({"content": "answer"})
        is False
    )
    assert (
        DelegationContract(success_criteria={"min_content_length": True}).validate_output({"content": "answer"})
        is False
    )


def test_custom_required_fields_still_validate_the_declared_schema() -> None:
    contract = DelegationContract(success_criteria={"required_fields": ["value"]})

    assert contract.validate_output({"value": 0}) is True
    assert contract.validate_output({"content": "answer"}) is False


@pytest.mark.asyncio
async def test_empty_specialist_result_is_emitted_as_failed_without_monkeypatching() -> None:
    registry = _Registry()
    dispatcher = _Dispatcher()
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=registry)
    thinking = SimpleNamespace(start=lambda *_a, **_k: None, append=lambda *_a, **_k: None, end=lambda *_a, **_k: None)

    result = await brain._dispatch_single(
        session_id="session",
        specialist_id="reasoning",
        prompt="answer the user",
        conversation=ConversationManager(),
        memory_ctx=MemoryContext(),
        dispatcher=dispatcher,
        thinking=thinking,
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
    )

    assert result.content == ""
    assert result.status == SpecialistStatus.FAILED
    assert result.ok is False
    assert registry.executed == ["reasoning"]
    assert dispatcher.activity[-1]["status"] == "failed"
