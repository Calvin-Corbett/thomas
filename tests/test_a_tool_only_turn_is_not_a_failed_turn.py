"""A turn that ran tools and wrote no prose did work, and must not report failure.

``DelegationContract`` now defaults to ``min_content_length: 1``, so
``validate_output`` returns False whenever a specialist finishes with empty or
whitespace-only content. ``_dispatch_single`` turned that into
``SpecialistStatus.FAILED`` even when ``result.error`` was None, and
``_handle_casual`` then replaced the turn with ``_chat_failure_message`` — the
user reads "I couldn't get an answer from the selected model" for a run in
which a tool did exactly what was asked.

Two failure directions are pinned here, because fixing the first one carelessly
causes the second:

1. A tool-only turn must not be reported as a failure (the lie).
2. It must not become a blank assistant message either (the silence) — an
   empty bubble is the "absence reads as health" shape in another costume.

A run that produced nothing at all — no prose, no tool calls — stays FAILED,
because "no answer" is then an honest description.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from thomas.chat.conversation import ConversationManager
from thomas.chat.memory_layers import MemoryContext
from thomas.marketplace.orchestrator.brain import OrchestratorBrain
from thomas.marketplace.orchestrator.protocol import SpecialistStatus


class _Dispatcher:
    def __init__(self) -> None:
        self.agent_activity: list[dict[str, object]] = []

    async def emit_text(self, text: str) -> None:
        _ = text

    async def emit(self, payload: dict[str, object]) -> None:
        _ = payload

    async def emit_done(self, **payload: object) -> None:
        _ = payload

    async def emit_delegation(self, **payload: object) -> None:
        _ = payload

    async def emit_agent_activity(self, **payload: object) -> None:
        self.agent_activity.append(dict(payload))

    async def emit_memory_refresh(self, **payload: object) -> None:
        _ = payload


class _Registry:
    def __init__(self, mapping: dict[str, object]) -> None:
        self.specialist_ids = list(mapping)
        self._mapping = mapping
        self.executed: list[str] = []

    def get(self, specialist_id: str) -> object | None:
        return self._mapping.get(specialist_id)

    def record_execution(self, specialist_id: str) -> None:
        self.executed.append(specialist_id)

    def build_routing_prompt(self, prompt: str) -> str:
        return f"route this: {prompt}"


class _ToolOnlySpecialist:
    """Acts through a tool and has nothing to add in prose."""

    capabilities = {"read", "tool"}

    async def execute(self, **kwargs: object):
        _ = kwargs
        yield {"type": "tool_start", "name": "send_task"}
        yield {"type": "tool_result", "name": "send_task", "result": "created", "ok": True}
        yield {"type": "done", "iterations": 1}


class _SilentSpecialist:
    """Produces nothing whatsoever."""

    capabilities = {"read"}

    async def execute(self, **kwargs: object):
        _ = kwargs
        yield {"type": "done", "iterations": 1}


async def _dispatch(specialist: object) -> object:
    brain = OrchestratorBrain(
        config=None,
        llm=None,
        memory_engine=None,
        registry=_Registry({"reasoning": specialist}),
    )
    thinking = SimpleNamespace(start=lambda *a, **k: None, append=lambda *a, **k: None, end=lambda *a, **k: None)
    return await brain._dispatch_single(
        session_id="sess-tool-only",
        specialist_id="reasoning",
        prompt="start a task for me",
        conversation=ConversationManager(),
        memory_ctx=MemoryContext(),
        dispatcher=_Dispatcher(),
        thinking=thinking,
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
    )


@pytest.mark.asyncio
async def test_a_specialist_that_only_ran_tools_is_not_reported_as_failed() -> None:
    result = await _dispatch(_ToolOnlySpecialist())

    assert result.error is None
    assert result.tool_calls, "the tool call is the work this turn performed"
    assert result.status == SpecialistStatus.COMPLETED
    assert result.ok is True


@pytest.mark.asyncio
async def test_a_specialist_that_produced_nothing_at_all_still_fails_honestly() -> None:
    result = await _dispatch(_SilentSpecialist())

    assert result.error is None
    assert not result.tool_calls
    assert result.status == SpecialistStatus.FAILED


@pytest.mark.asyncio
async def test_a_failed_contract_on_real_prose_still_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The carve-out is for missing prose only, not for contracts in general."""

    class _ProseSpecialist:
        capabilities = {"read", "tool"}

        async def execute(self, **kwargs: object):
            _ = kwargs
            yield {"type": "tool_start", "name": "ls"}
            yield {"type": "tool_result", "name": "ls", "result": "ok", "ok": True}
            yield {"type": "text", "text": "answer"}
            yield {"type": "done", "iterations": 1}

    monkeypatch.setattr(
        "thomas.marketplace.orchestrator.brain.DelegationContract.validate_output",
        lambda self, output: False,
    )
    result = await _dispatch(_ProseSpecialist())

    assert result.content.strip() == "answer"
    assert result.status == SpecialistStatus.FAILED
