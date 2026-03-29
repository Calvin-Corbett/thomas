from __future__ import annotations

import asyncio
from types import SimpleNamespace

from thomas.core.llm_shared import StreamEvent
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.tools import ToolSpecialist


class _FakeCodexLlm:
    def __init__(self) -> None:
        self.config = SimpleNamespace(provider="codex")
        self.calls: list[dict] = []

    async def stream_chat(self, messages, tools=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "tools": list(tools or [])})
        yield StreamEvent(type="tool_call_start", data={"id": "t1", "name": "Get-ChildItem"})
        yield StreamEvent(type="tool_call_end", data={"id": "t1", "name": "Get-ChildItem", "output": "README.md"})
        yield StreamEvent(type="token", data={"text": "README.md, pyproject.toml, LICENSE"})
        yield StreamEvent(type="done", data={})


def test_tool_specialist_uses_codex_streaming_with_tools_enabled() -> None:
    specialist = ToolSpecialist(config=None, llm=_FakeCodexLlm(), tools=None)
    contract = DelegationContract(
        specialist_id="tools",
        task_description="List repo files",
        allowed_tools={"tool_execution"},
        timeout_seconds=60,
        max_iterations=5,
        input_context={},
    )
    token = CapabilityToken(
        specialist_id="tools",
        session_id="sess-tools",
        allowed_tools={"tool_execution"},
        autonomy_level=4,
    )

    async def _run():
        events = []
        async for event in specialist.execute(
            contract=contract,
            token=token,
            prompt="Use your file tools and list three top-level files in the repo.",
            conversation_context=[],
            memory_context="",
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())
    event_types = [str(event.get("type") or "") for event in events]

    assert event_types == ["tool_start", "tool_result", "text", "done"]
    assert specialist.llm.calls and specialist.llm.calls[0]["tools"]
    assert events[-1]["tool_calls"] == 1
