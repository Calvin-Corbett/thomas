from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from thomas.chat.conversation import ConversationManager
from thomas.chat.memory_layers import MemoryContext
from thomas.marketplace.orchestrator import brain as brain_mod
from thomas.marketplace.orchestrator.brain import OrchestratorBrain
from thomas.marketplace.orchestrator.protocol import DelegationResult, RouteDecision, SpecialistStatus


class _Dispatcher:
    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.events: list[dict[str, object]] = []
        self.done_payloads: list[dict[str, object]] = []
        self.delegations: list[dict[str, object]] = []
        self.agent_activity: list[dict[str, object]] = []
        self.memory_refreshes: list[dict[str, object]] = []

    async def emit_text(self, text: str) -> None:
        self.text_parts.append(str(text))

    async def emit(self, payload: dict[str, object]) -> None:
        self.events.append(dict(payload))

    async def emit_done(self, **payload: object) -> None:
        self.done_payloads.append(dict(payload))

    async def emit_delegation(self, **payload: object) -> None:
        self.delegations.append(dict(payload))

    async def emit_agent_activity(self, **payload: object) -> None:
        self.agent_activity.append(dict(payload))

    async def emit_memory_refresh(self, **payload: object) -> None:
        self.memory_refreshes.append(dict(payload))


class _Registry:
    def __init__(self, specialist_ids: list[str] | None = None, mapping: dict[str, object] | None = None) -> None:
        self.specialist_ids = ["reasoning"] if specialist_ids is None else list(specialist_ids)
        self._mapping = mapping or {}
        self.executed: list[str] = []

    def get(self, specialist_id: str) -> object | None:
        return self._mapping.get(specialist_id)

    def record_execution(self, specialist_id: str) -> None:
        self.executed.append(specialist_id)

    def build_routing_prompt(self, prompt: str) -> str:
        return f"route this: {prompt}"


class _ChatDictLLM:
    async def chat(self, *, messages: list[dict[str, object]]) -> dict[str, object]:
        _ = messages
        return {
            "text": '{"specialists":["tools","missing"],"parallel":true,"reasoning":"json route","confidence":0.93}'
        }


class _CompleteLLM:
    async def complete(self, *, prompt: str) -> str:
        return f"completed:{prompt.splitlines()[0]}"


class _StreamingSpecialist:
    capabilities = {"read", "tool"}

    async def execute(self, **kwargs: object):
        _ = kwargs
        yield {"type": "thinking", "text": "plan"}
        yield {"type": "tool_start", "name": "ls"}
        yield {"type": "tool_result", "name": "ls", "result": "ok", "ok": True}
        yield {"type": "text", "text": "answer"}
        yield {"type": "done", "iterations": 2}


class _ErrorSpecialist:
    capabilities = {"read"}

    async def execute(self, **kwargs: object):
        _ = kwargs
        raise asyncio.TimeoutError
        yield  # pragma: no cover


class _MemoryCoordinator:
    def __init__(self, *args: object, **kwargs: object) -> None:
        _ = args
        _ = kwargs
        self.captured: list[dict[str, object]] = []

    async def refresh(self, **kwargs: object) -> MemoryContext:
        _ = kwargs
        return MemoryContext(working="working", episodic="episodic", semantic="semantic")

    async def capture_episode(self, **kwargs: object) -> None:
        self.captured.append(dict(kwargs))


@pytest.mark.asyncio
async def test_classify_and_route_uses_llm_json_and_default_fallbacks() -> None:
    brain = OrchestratorBrain(
        config=None,
        llm=_ChatDictLLM(),
        memory_engine=None,
        registry=_Registry(["reasoning", "tools"]),
    )

    routed = await brain._classify_and_route("inspect the repo", ConversationManager(), MemoryContext())
    assert routed.specialists == ["tools"]
    assert routed.parallel is True
    assert routed.reasoning == "json route"

    empty = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=_Registry([]))
    fallback = await empty._classify_and_route("anything", ConversationManager(), MemoryContext())
    assert fallback.specialists == ["reasoning"]
    assert "No specialists available" in fallback.reasoning


@pytest.mark.asyncio
async def test_classify_and_route_falls_back_when_llm_output_is_bad_json() -> None:
    class _BadLLM:
        async def chat(self, *, messages: list[dict[str, object]]) -> dict[str, object]:
            _ = messages
            return {"text": "not-json"}

    brain = OrchestratorBrain(
        config=None,
        llm=_BadLLM(),
        memory_engine=None,
        registry=_Registry(["reasoning", "coding"]),
    )

    routed = await brain._classify_and_route("write code", ConversationManager(), MemoryContext())
    assert routed.specialists == ["reasoning"]
    assert routed.confidence == 0.5


@pytest.mark.asyncio
async def test_call_llm_supports_chat_and_complete_clients() -> None:
    brain = OrchestratorBrain(config=None, llm=_CompleteLLM(), memory_engine=None, registry=_Registry())
    text = await brain._call_llm([{"role": "user", "content": "hello"}])
    assert text.startswith("completed:user:")

    class _ContentLLM:
        async def chat(self, *, messages: list[dict[str, object]]) -> object:
            _ = messages
            return SimpleNamespace(content="content-object")

    brain = OrchestratorBrain(config=None, llm=_ContentLLM(), memory_engine=None, registry=_Registry())
    assert await brain._call_llm([{"role": "user", "content": "hello"}]) == "content-object"


@pytest.mark.asyncio
async def test_dispatch_single_handles_missing_specialist_validation_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=_Registry(["reasoning"], {}))
    dispatcher = _Dispatcher()
    thinking = SimpleNamespace(start=lambda *a, **k: None, append=lambda *a, **k: None, end=lambda *a, **k: None)

    missing = await brain._dispatch_single(
        session_id="sess-1",
        specialist_id="missing",
        prompt="inspect",
        conversation=ConversationManager(),
        memory_ctx=MemoryContext(),
        dispatcher=dispatcher,
        thinking=thinking,
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
    )
    assert missing.status == SpecialistStatus.FAILED
    assert "not found" in str(missing.error)

    registry = _Registry(["reasoning"], {"reasoning": _StreamingSpecialist()})
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=registry)
    monkeypatch.setattr(
        "thomas.marketplace.orchestrator.brain.DelegationContract.validate_output",
        lambda self, output: False,
    )
    invalid = await brain._dispatch_single(
        session_id="sess-1",
        specialist_id="reasoning",
        prompt="inspect",
        conversation=ConversationManager(),
        memory_ctx=MemoryContext(),
        dispatcher=dispatcher,
        thinking=thinking,
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
    )
    assert invalid.status == SpecialistStatus.FAILED
    assert dispatcher.agent_activity[-1]["status"] == "failed"

    timeout_registry = _Registry(["reasoning"], {"reasoning": _ErrorSpecialist()})
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=timeout_registry)
    timeout = await brain._dispatch_single(
        session_id="sess-1",
        specialist_id="reasoning",
        prompt="inspect",
        conversation=ConversationManager(),
        memory_ctx=MemoryContext(),
        dispatcher=dispatcher,
        thinking=thinking,
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
    )
    assert timeout.status == SpecialistStatus.TIMEOUT


@pytest.mark.asyncio
async def test_dispatch_parallel_and_synthesise_cover_fallback_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=_Registry(["a", "b"]))
    dispatcher = _Dispatcher()
    thinking = SimpleNamespace(start=lambda *a, **k: None, append=lambda *a, **k: None, end=lambda *a, **k: None)

    async def _fake_dispatch_single(**kwargs: object) -> DelegationResult:
        specialist_id = str(kwargs["specialist_id"])
        if specialist_id == "b":
            raise RuntimeError("boom")
        return DelegationResult(specialist_id=specialist_id, content="ok")

    monkeypatch.setattr(brain, "_dispatch_single", _fake_dispatch_single)
    results = await brain._dispatch_parallel(
        session_id="sess-1",
        specialists=["a", "b"],
        prompt="parallel",
        conversation=ConversationManager(),
        memory_ctx=MemoryContext(),
        dispatcher=dispatcher,
        thinking=thinking,
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
    )
    assert len(results) == 2
    assert any(r.status == SpecialistStatus.FAILED for r in results)

    error_text = await brain._synthesise(
        prompt="help",
        results=[DelegationResult(status=SpecialistStatus.FAILED, error="bad")],
        memory_ctx=MemoryContext(),
        mode="auto",
    )
    assert "encountered issues" in error_text.lower()

    extracted = await brain._synthesise(
        prompt="help",
        results=[DelegationResult(content='{"response":"usable text"}')],
        memory_ctx=MemoryContext(),
        mode="auto",
    )
    assert extracted == "usable text"

    class _FailLLM:
        async def chat(self, *, messages: list[dict[str, object]]) -> str:
            _ = messages
            raise RuntimeError("no synthesis")

    brain = OrchestratorBrain(config=None, llm=_FailLLM(), memory_engine=None, registry=_Registry())
    joined = await brain._synthesise(
        prompt="help",
        results=[
            DelegationResult(specialist_id="one", content="first"),
            DelegationResult(specialist_id="two", content="second"),
        ],
        memory_ctx=MemoryContext(),
        mode="auto",
    )
    assert joined == "first\n\nsecond"


@pytest.mark.asyncio
async def test_handle_casual_and_actionable_emit_done_and_stream_output(monkeypatch: pytest.MonkeyPatch) -> None:
    created_coordinators: list[_MemoryCoordinator] = []

    def _fake_memory_coordinator(*args: object, **kwargs: object) -> _MemoryCoordinator:
        coord = _MemoryCoordinator(*args, **kwargs)
        created_coordinators.append(coord)
        return coord

    monkeypatch.setattr("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _fake_memory_coordinator)
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=_Registry(["reasoning"]))
    dispatcher = _Dispatcher()

    async def _failed_dispatch_single(**kwargs: object) -> DelegationResult:
        memory_ctx = kwargs["memory_ctx"]
        assert isinstance(memory_ctx, MemoryContext)
        assert "digest text" in memory_ctx.working
        return DelegationResult(
            specialist_id="reasoning",
            status=SpecialistStatus.FAILED,
            error="broken",
        )

    monkeypatch.setattr(brain, "_dispatch_single", _failed_dispatch_single)
    conversation = ConversationManager().append_message("assistant", "Earlier response")
    updated = await brain._handle_casual(
        session_id="sess-1",
        conversation=conversation,
        prompt="How is the background work going?",
        dispatcher=dispatcher,
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
        turn_start=0.0,
        reply_kind="conversation",
        active_task_digest="digest text",
    )
    assert "Sorry, I had trouble with that." in "".join(dispatcher.text_parts)
    assert updated.last_assistant_message() == "Sorry, I had trouble with that."
    assert created_coordinators[-1].captured
    assert dispatcher.done_payloads[-1]["thinking_summary"] == "conversation"

    async def _routed(*args: object, **kwargs: object) -> RouteDecision:
        _ = args
        _ = kwargs
        return RouteDecision(specialists=["reasoning"], parallel=False, reasoning="direct")

    async def _successful_dispatch_single(**kwargs: object) -> DelegationResult:
        return DelegationResult(
            specialist_id="reasoning",
            content='{"response":"clean answer"}',
            tool_calls=[{"type": "tool_result", "name": "ls"}],
            iterations=2,
            tokens_used=17,
        )

    monkeypatch.setattr(brain, "_classify_and_route", _routed)
    monkeypatch.setattr(brain, "_dispatch_single", _successful_dispatch_single)
    dispatcher = _Dispatcher()
    actionable = await brain._handle_actionable(
        session_id="sess-2",
        conversation=ConversationManager(),
        prompt="Use your tools and answer.",
        dispatcher=dispatcher,
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
        turn_start=0.0,
    )
    assert dispatcher.memory_refreshes
    assert "".join(dispatcher.text_parts).startswith("Working on that")
    assert "clean answer" in (actionable.last_assistant_message() or "")
    assert dispatcher.done_payloads[-1]["tool_calls"] == 1


def test_background_status_helpers_cover_active_failed_and_mixed_states() -> None:
    assert brain_mod._wants_background_status("what is the status?") is True
    assert brain_mod._wants_background_status("tell me a joke") is False

    assert (
        brain_mod._should_answer_background_status_directly("what is the status of the background worker?", []) is True
    )
    assert brain_mod._should_answer_background_status_directly("tell me a joke", []) is False

    active = brain_mod._summarize_background_status(
        [{"state": "running", "summary": "Build release", "last_progress": "Step 2"}]
    )
    assert "still running" in active.lower()
    assert "Build release" in active

    failed = brain_mod._summarize_background_status(
        [{"state": "failed", "summary": "Deploy release", "last_progress": "Auth failed"}]
    )
    assert "finished with issues" in failed.lower()

    mixed = brain_mod._summarize_background_status(
        [
            {"state": "completed", "summary": "One"},
            {"state": "failed", "summary": "Two"},
            {"state": "paused", "summary": "Three"},
        ]
    )
    assert "mixed outcomes" in mixed.lower()


@pytest.mark.asyncio
async def test_handle_background_status_without_tasks_and_call_llm_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenMemoryCoordinator:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args
            _ = kwargs

        async def capture_episode(self, **kwargs: object) -> None:
            _ = kwargs
            raise RuntimeError("memory unavailable")

    monkeypatch.setattr("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _BrokenMemoryCoordinator)
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=_Registry(["reasoning"]))
    dispatcher = _Dispatcher()

    updated = await brain._handle_background_status(
        session_id="sess-bg",
        conversation=ConversationManager(),
        prompt="what's the status?",
        dispatcher=dispatcher,
        turn_start=0.0,
        active_tasks=[],
    )
    assert "No background work is running" in "".join(dispatcher.text_parts)
    assert updated.last_assistant_message() == "No background work is running in this thread."
    assert dispatcher.done_payloads[-1]["thinking_summary"] == "background_status"

    assert await brain._call_llm([{"role": "user", "content": "hello"}]) == ""

    class _FailChatLLM:
        async def chat(self, *, messages: list[dict[str, object]]) -> str:
            _ = messages
            raise RuntimeError("chat failed")

    brain = OrchestratorBrain(config=None, llm=_FailChatLLM(), memory_engine=None, registry=_Registry())
    with pytest.raises(RuntimeError):
        await brain._call_llm([{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_synthesise_and_casual_cover_empty_and_passthrough_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=_Registry(["reasoning"]))

    empty = await brain._synthesise(
        prompt="help",
        results=[DelegationResult(content="   ")],
        memory_ctx=MemoryContext(),
        mode="auto",
    )
    assert "wasn't able to generate a response" in empty

    passthrough = await brain._synthesise(
        prompt="help",
        results=[DelegationResult(content="{not actually json}")],
        memory_ctx=MemoryContext(),
        mode="auto",
    )
    assert passthrough == "{not actually json}"

    created_coordinators: list[_MemoryCoordinator] = []

    def _fake_memory_coordinator(*args: object, **kwargs: object) -> _MemoryCoordinator:
        coord = _MemoryCoordinator(*args, **kwargs)
        created_coordinators.append(coord)
        return coord

    monkeypatch.setattr("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _fake_memory_coordinator)

    async def _successful_dispatch_single(**kwargs: object) -> DelegationResult:
        return DelegationResult(specialist_id="reasoning", content="direct answer", tokens_used=5)

    monkeypatch.setattr(brain, "_dispatch_single", _successful_dispatch_single)
    dispatcher = _Dispatcher()
    updated = await brain._handle_casual(
        session_id="sess-casual",
        conversation=ConversationManager(),
        prompt="hello there",
        dispatcher=dispatcher,
        mode="auto",
        autonomy_level=3,
        token_economy="optimal",
        turn_start=0.0,
        reply_kind="casual",
        active_task_digest="",
    )
    assert updated.last_assistant_message() == "direct answer"
    assert created_coordinators[-1].captured
    assert dispatcher.done_payloads[-1]["thinking_summary"] == "casual"
