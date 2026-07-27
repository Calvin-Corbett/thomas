from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from thomas.chat.conversation import ConversationManager
from thomas.chat.memory_layers import MemoryContext
from thomas.marketplace.orchestrator import brain as brain_mod
from thomas.marketplace.orchestrator.brain import OrchestratorBrain
from thomas.marketplace.orchestrator.protocol import DelegationResult, SpecialistStatus
from thomas.marketplace.orchestrator.registry import SpecialistRegistry


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


class _TransientErrorSpecialist:
    capabilities = {"read"}

    def __init__(self) -> None:
        self.attempts = 0

    async def execute(self, **kwargs: object):
        _ = kwargs
        self.attempts += 1
        yield {"type": "thinking", "text": "starting"}
        if self.attempts == 1:
            yield {"type": "error", "error": "temporary model connection failure"}
            return
        yield {"type": "text", "text": "recovered answer"}
        yield {"type": "done", "iterations": 1}


class _BoundSpecialist:
    specialist_id = "reasoning"
    description = "bound specialist"
    capabilities = {"reasoning"}

    def __init__(self, llm: object) -> None:
        self.llm = llm


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


def test_registry_binds_request_scoped_specialist_copies() -> None:
    original_llm = object()
    request_llm = object()
    registry = SpecialistRegistry()
    registry.register(_BoundSpecialist(original_llm))

    bound = registry.bound_to_llm(request_llm)

    assert bound is not registry
    assert bound.get("reasoning") is not registry.get("reasoning")
    assert registry.get("reasoning").llm is original_llm
    assert bound.get("reasoning").llm is request_llm

    bound.record_execution("reasoning")
    assert registry.get_stats()["reasoning"]["executions"] == 1


def test_chat_failure_message_explains_auth_and_transient_failures() -> None:
    auth = brain_mod._chat_failure_message("ChatGPT OAuth is not connected. Sign in first.")
    transient = brain_mod._chat_failure_message("connection reset")
    unknown = brain_mod._chat_failure_message("broken")

    assert "ChatGPT model isn't connected" in auth
    assert "Local model" in auth
    assert "retried once" in transient
    assert "retried once" in unknown


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
async def test_dispatch_single_retries_one_zero_output_transient_failure() -> None:
    specialist = _TransientErrorSpecialist()
    registry = _Registry(["reasoning"], {"reasoning": specialist})
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=registry)
    dispatcher = _Dispatcher()
    thinking = SimpleNamespace(start=lambda *a, **k: None, append=lambda *a, **k: None, end=lambda *a, **k: None)

    result = await brain._dispatch_single(
        session_id="sess-retry",
        specialist_id="reasoning",
        prompt="hello",
        conversation=ConversationManager(),
        memory_ctx=MemoryContext(),
        dispatcher=dispatcher,
        thinking=thinking,
        mode="auto",
        autonomy_level=1,
        token_economy="optimal",
    )

    assert specialist.attempts == 2
    assert result.status == SpecialistStatus.COMPLETED
    assert result.content == "recovered answer"
    assert result.error is None


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
async def test_model_owned_handler_emits_done_and_streams_failure(monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert kwargs["images"] == [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
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
        images=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}],
    )
    expected_failure = (
        "I couldn't get an answer from the selected model. I retried once; please try again or choose another model."
    )
    assert expected_failure in "".join(dispatcher.text_parts)
    assert updated.last_assistant_message() == expected_failure
    assert created_coordinators[-1].captured
    assert dispatcher.done_payloads[-1]["thinking_summary"] == "conversation"

    # There is intentionally no separate actionable handler. The same model
    # path receives tools and decides whether to call them.
    # No canned "Working on that —" prefix: the only visible text is the model's
    # actual answer. The reply must not start with a templated acknowledgment.


def test_background_status_formatter_covers_active_failed_and_mixed_states() -> None:
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
    # Round-4 M1 guard: EVERY bucket is surfaced — the paused ("other") row is not
    # dropped just because completed/failed rows coexist (the old early-return did).
    assert "One" in mixed and "(completed)" in mixed
    assert "Two" in mixed and "finished with issues" in mixed.lower()
    assert "Three" in mixed and "needs attention" in mixed.lower()

    # Only non-terminal/odd states present -> the mixed-outcomes label still applies.
    only_other = brain_mod._summarize_background_status(
        [{"state": "blocked", "summary": "Stuck"}, {"state": "awaiting_proof", "summary": "Pending"}]
    )
    assert "mixed outcomes" in only_other.lower()
    assert "Stuck" in only_other and "Pending" in only_other


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
        return DelegationResult(
            specialist_id="reasoning",
            content="direct answer",
            tokens_used=5,
            tool_calls=[{"type": "tool_result", "name": "operate", "ok": True}],
        )

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
    assert created_coordinators[-1].captured[-1]["tool_calls"] == [
        {"type": "tool_result", "name": "operate", "ok": True}
    ]
    assert dispatcher.done_payloads[-1]["thinking_summary"] == "casual"
    assert dispatcher.done_payloads[-1]["tool_calls"] == 1
