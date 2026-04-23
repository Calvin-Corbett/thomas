from __future__ import annotations

from types import SimpleNamespace

from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.tools import (
    ToolSpecialist,
)


class _FakeCodexEvent:
    def __init__(self, event_type: str, data: dict[str, object] | None = None) -> None:
        self.type = event_type
        self.data = data or {}


class _FakeCodexLLM:
    def __init__(self, events: list[_FakeCodexEvent]) -> None:
        self.config = SimpleNamespace(provider="codex", reasoning_effort="medium")
        self._events = list(events)
        self.seen_messages: list[dict[str, object]] | None = None
        self.seen_tools: list[dict[str, object]] | None = None
        self.seen_effort: str | None = None

    async def stream_chat(self, *, messages: list[dict[str, object]], tools: list[dict[str, object]]):
        self.seen_messages = list(messages)
        self.seen_tools = list(tools)
        self.seen_effort = str(getattr(self.config, "reasoning_effort", ""))
        for event in self._events:
            yield event


async def _collect_events(specialist: ToolSpecialist, prompt: str) -> list[dict[str, object]]:
    contract = DelegationContract(specialist_id="tools", task_description=prompt)
    token = CapabilityToken(
        specialist_id="tools",
        session_id="tools-test",
        allowed_tools={"tool_execution", "file_operations", "filesystem", "shell"},
        autonomy_level=3,
    )
    events: list[dict[str, object]] = []
    async for event in specialist._execute_impl(
        contract=contract,
        token=token,
        prompt=prompt,
        conversation_context=[],
        memory_context="",
    ):
        events.append(event)
    return events


def _direct_token() -> CapabilityToken:
    return CapabilityToken(
        specialist_id="tools",
        session_id="tools-test",
        allowed_tools={"tool_execution", "file_operations", "filesystem", "shell"},
        autonomy_level=3,
    )
