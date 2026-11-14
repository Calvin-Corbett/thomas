"""A Chat reply must never end in "The selected model timed out ... try again."

Measured live 2026-09-23: a self-fix request read files inline -- 25 tool
calls, zero ``send_task`` -- until the 120s wall cut it off, blaming the
model and asking to try again, even on Autopilot. You asked: "he should
never reply back with this didnt work say go and ill do it again."

Round 1 restricted the retry *token* but ``ReasoningSpecialist`` never
consulted it when deciding which tools to *offer* -- the retry still offered
every read tool, the model still tried them, and each got a confusing
denial with nothing to summarise. Round 2 (this file) pins the real fix:
``thomas/marketplace/specialists/final_pass.py`` builds a contract carrying
``final_pass=True`` and the first pass's own findings, which the REAL
``ReasoningSpecialist`` (driven by a fake model, never a fake specialist,
for the tool-offering tests) reads to offer no read tools at all.

Every specialist/store here is a stub; nothing reaches a real model, a
subprocess, or the network.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.chat.conversation import ConversationManager
from thomas.chat.memory_layers import MemoryContext
from thomas.chat.session_namespace_binding import bind_surface_namespace
from thomas.chat.session_store import SessionMeta, SessionStore
from thomas.core.config import AppConfig, ModelConfig, ToolsConfig
from thomas.marketplace.orchestrator.brain import OrchestratorBrain, _chat_failure_message
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract, SpecialistStatus
from thomas.marketplace.specialists import final_pass
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist
from thomas.preferences._prefs import AutonomyPrefs
from thomas.preferences.store import PreferencesPatch, PreferencesStore
from thomas.server import dial_elevation
from thomas.server.chat_runtime_policy import resolve_chat_runtime_policy

# ── shared fakes ──────────────────────────────────────────────────────────

_THINKING_STUB = SimpleNamespace(start=lambda *a, **k: None, append=lambda *a, **k: None, end=lambda *a, **k: None)


async def _noop_send_task(**_k: object) -> dict[str, object]:
    return {"ok": True}


class _Dispatcher:
    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.done_payloads: list[dict[str, object]] = []

    async def emit_text(self, text: str) -> None:
        self.text_parts.append(str(text))

    async def emit_done(self, **payload: object) -> None:
        self.done_payloads.append(dict(payload))

    async def _noop(self, *_a: object, **_k: object) -> None:
        pass

    emit = _noop
    emit_delegation = _noop
    emit_agent_activity = _noop
    emit_memory_refresh = _noop


class _Registry:
    def __init__(self, mapping: dict[str, object]) -> None:
        self.specialist_ids = list(mapping)
        self._mapping = mapping
        self.executed: list[str] = []

    def get(self, specialist_id: str) -> object | None:
        return self._mapping.get(specialist_id)

    def record_execution(self, specialist_id: str) -> None:
        self.executed.append(specialist_id)


class _MemoryCoordinatorStub:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def refresh(self, **kwargs: object) -> MemoryContext:
        return MemoryContext(working="", episodic="", semantic="")

    async def capture_episode(self, **kwargs: object) -> None:
        pass


async def _dispatch(specialist: object, specialist_id: str = "reasoning", **overrides: object):
    brain = OrchestratorBrain(
        config=None, llm=None, memory_engine=None, registry=_Registry({specialist_id: specialist})
    )
    return await brain._dispatch_single(
        session_id="sess-final-pass",
        specialist_id=specialist_id,
        prompt="Find and fix the timeout bug.",
        conversation=ConversationManager(),
        memory_ctx=MemoryContext(),
        dispatcher=_Dispatcher(),
        thinking=_THINKING_STUB,
        mode="auto",
        autonomy_level=5,
        token_economy="optimal",
        stream_text_events=True,
        **overrides,
    )


def _local_config() -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", provider="openai_compat", base_url="http://x/v1", model="m")},
        default_model="local",
    )


class _ScriptedLLM:
    """A fake model whose ``stream_chat`` is scripted call-by-call."""

    model = "gpt-6-sol"

    def __init__(self, script: list[list[SimpleNamespace]]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, object]] = []

    async def stream_chat(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        for event in self._script.pop(0) if self._script else []:
            yield event


def _ev(event_type: str, **data: object) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, data=data)


def _primary_contract_and_token(*, send_task_cb: object | None) -> tuple[DelegationContract, CapabilityToken]:
    contract = DelegationContract(
        specialist_id="reasoning",
        input_context={"send_task": send_task_cb, "autonomy": {"level": 5, "directive": ""}},
    )
    token = CapabilityToken(
        specialist_id="reasoning",
        allowed_tools={"fs.read_file", "fs.list_dir", "fs.search", "skills.list", "skills.use", "send_task"},
    )
    return contract, token


class _TimesOutThenHandsOffSpecialist:
    """Pass 1 times out mid-tool; pass 2's restricted token denies fs.read_file."""

    capabilities = {"reasoning"}

    def __init__(self) -> None:
        self.tokens: list[object] = []

    async def execute(self, *, contract, token, prompt, conversation_context, memory_context):
        _ = (contract, prompt, conversation_context, memory_context)
        self.tokens.append(token)
        if len(self.tokens) == 1:
            yield {"type": "tool_start", "name": "fs.read_file"}
            yield {"type": "tool_result", "name": "fs.read_file", "ok": True, "result": "brain.py:366"}
            yield {"type": "error", "error": "Specialist 'reasoning' timed out after 120.0s"}
            return
        assert not token.permits_tool("fs.read_file"), "the final pass must deny explore tools"
        yield {"type": "tool_start", "name": "send_task"}
        yield {"type": "tool_result", "name": "send_task", "ok": True, "result": "created"}
        yield {"type": "done", "iterations": 1}


class _TimesOutThenSummarizesSpecialist:
    """No hand-off available: the final pass must still conclude in prose."""

    capabilities = {"reasoning"}

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, *, contract, token, prompt, conversation_context, memory_context):
        _ = (contract, token, prompt, conversation_context, memory_context)
        self.calls += 1
        if self.calls == 1:
            yield {"type": "text", "text": "Still reading the repo for the root cause. "}
            yield {"type": "error", "error": "Specialist 'reasoning' timed out after 120.0s"}
            return
        yield {"type": "text", "text": "Here is what I found so far and what I'd do next."}


class _NonReasoningTimesOut:
    capabilities = {"coding"}

    async def execute(self, **kwargs: object):
        _ = kwargs
        yield {"type": "error", "error": "Specialist 'coding' timed out after 120.0s"}


class _AlwaysTimesOutSpecialist:
    """Both passes hit the deadline -- the worst case for Requirement 1."""

    capabilities = {"reasoning"}

    async def execute(self, **kwargs: object):
        _ = kwargs
        yield {"type": "text", "text": "Reading file one of many. "}
        yield {"type": "error", "error": "Specialist 'reasoning' timed out after 120.0s"}


# ── C1: the final pass is tool-free and sees the first pass's findings ───


@pytest.mark.asyncio
async def test_a_timed_out_pass_gets_one_final_restricted_pass_that_hands_off() -> None:
    specialist = _TimesOutThenHandsOffSpecialist()
    result = await _dispatch(specialist, send_task=_noop_send_task)

    assert len(specialist.tokens) == 2, "the timeout must trigger exactly one more pass"
    assert result.status == SpecialistStatus.COMPLETED
    assert result.ok is True
    assert result.attempts == 2
    tool_names = [call.get("name") for call in result.tool_calls]
    assert "fs.read_file" in tool_names, "the first pass's real work is kept, not discarded"
    assert "send_task" in tool_names, "the final pass handed off instead of timing out"


@pytest.mark.asyncio
async def test_a_timed_out_pass_with_no_handoff_concludes_in_prose() -> None:
    specialist = _TimesOutThenSummarizesSpecialist()
    result = await _dispatch(specialist)

    assert specialist.calls == 2
    assert result.status == SpecialistStatus.COMPLETED
    assert "what I found so far" in result.content
    assert "timed out" not in result.content.lower()
    # Requirement: "join the two passes' texts with a separator ... keep the
    # saved history equal to what was shown."
    assert "\n\n" in result.content


@pytest.mark.asyncio
async def test_a_specialist_with_no_handoff_tools_granted_gets_no_final_pass() -> None:
    # Only Chat's reasoning specialist has the explore/hand-off tool split.
    result = await _dispatch(_NonReasoningTimesOut(), specialist_id="coding")

    assert result.status == SpecialistStatus.TIMEOUT
    assert result.error is not None


@pytest.mark.asyncio
async def test_the_real_reasoning_specialist_final_pass_offers_exactly_send_task_or_nothing() -> None:
    async def _offered_tool_names(send_task_allowed: bool) -> list[str | None]:
        llm = _ScriptedLLM([[_ev("token", text="Summary.")]])
        specialist = ReasoningSpecialist(config=None, llm=llm, tools=None)
        contract, token = _primary_contract_and_token(send_task_cb=_noop_send_task if send_task_allowed else None)
        fc = final_pass.final_pass_contract(
            contract, timeout_seconds=20.0, tool_calls=[], send_task_allowed=send_task_allowed
        )
        ft = final_pass.final_pass_token(token, send_task_allowed=send_task_allowed)
        async for _event in specialist.execute(
            contract=fc, token=ft, prompt="p", conversation_context=[], memory_context=""
        ):
            pass
        return [((t.get("function") or {}).get("name")) for t in (llm.calls[0]["tools"] or [])]

    assert await _offered_tool_names(True) == ["send_task"]
    assert await _offered_tool_names(False) == []


@pytest.mark.asyncio
async def test_the_real_reasoning_specialists_final_pass_messages_contain_the_first_passs_findings() -> None:
    llm = _ScriptedLLM([[_ev("token", text="Summary.")]])
    specialist = ReasoningSpecialist(config=None, llm=llm, tools=None)
    contract, token = _primary_contract_and_token(send_task_cb=None)
    tool_calls = [{"type": "tool_result", "name": "fs.read_file", "ok": True, "result": "SECRET_FINDING brain.py:366"}]
    fc = final_pass.final_pass_contract(contract, timeout_seconds=20.0, tool_calls=tool_calls, send_task_allowed=False)
    ft = final_pass.final_pass_token(token, send_task_allowed=False)
    async for _event in specialist.execute(
        contract=fc, token=ft, prompt="p", conversation_context=[], memory_context=""
    ):
        pass

    system_content = llm.calls[0]["messages"][0]["content"]
    assert "SECRET_FINDING" in system_content


@pytest.mark.asyncio
async def test_a_read_tool_attempt_in_the_final_pass_is_refused_and_still_concludes() -> None:
    class _Tools:
        def __init__(self) -> None:
            self.executed: list[str] = []

        def get(self, name: str) -> SimpleNamespace:
            return SimpleNamespace(name=name)

        async def execute(self, name: str, args: dict) -> SimpleNamespace:
            self.executed.append(name)
            return SimpleNamespace(ok=True, data="a real file read must never happen here")

    llm = _ScriptedLLM(
        [
            [_ev("tool_call_end", id="c1", name="fs.read_file", arguments="{}")],
            [_ev("token", text="Here is what I found and what I would do next.")],
        ]
    )
    tools = _Tools()
    specialist = ReasoningSpecialist(config=None, llm=llm, tools=tools)
    contract, token = _primary_contract_and_token(send_task_cb=_noop_send_task)
    fc = final_pass.final_pass_contract(contract, timeout_seconds=20.0, tool_calls=[], send_task_allowed=True)
    ft = final_pass.final_pass_token(token, send_task_allowed=True)
    events = [
        event
        async for event in specialist.execute(
            contract=fc, token=ft, prompt="p", conversation_context=[], memory_context=""
        )
    ]

    assert not tools.executed, "a read tool the final pass never offered must be refused, not executed"
    assert not any(e.get("type") == "error" for e in events)
    assert any(e.get("type") == "done" for e in events)


# ── I2: the turn's own deadline, separate from tool_timeout_s ────────────


def test_turn_deadline_s_bounds_the_primary_pass_leaving_the_reserve() -> None:
    assert final_pass.resolve_turn_deadline_s(None) == final_pass.DEFAULT_TURN_DEADLINE_S
    assert final_pass.resolve_turn_deadline_s(SimpleNamespace(turn_deadline_s=90.0)) == 90.0
    assert final_pass.primary_pass_timeout_s(150.0) == 150.0 - final_pass.FINAL_PASS_RESERVE_S


@pytest.mark.asyncio
async def test_dispatch_bounds_the_primary_pass_by_turn_deadline_s_not_tool_timeout_s() -> None:
    class _CapturingSpecialist:
        capabilities = {"reasoning"}

        def __init__(self) -> None:
            self.seen_timeout: float | None = None

        async def execute(self, *, contract, token, prompt, conversation_context, memory_context):
            _ = (token, prompt, conversation_context, memory_context)
            self.seen_timeout = contract.timeout_seconds
            yield {"type": "text", "text": "ok"}
            yield {"type": "done", "iterations": 1}

    specialist = _CapturingSpecialist()
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=_Registry({"reasoning": specialist}))
    brain.runtime_policy = SimpleNamespace(
        tools=SimpleNamespace(tool_timeout_s=120, turn_deadline_s=60), quality=None, memory=None
    )
    await brain._dispatch_single(
        session_id="sess-i2",
        specialist_id="reasoning",
        prompt="p",
        conversation=ConversationManager(),
        memory_ctx=MemoryContext(),
        dispatcher=_Dispatcher(),
        thinking=_THINKING_STUB,
        mode="auto",
        autonomy_level=5,
        token_economy="optimal",
    )
    assert specialist.seen_timeout == 60 - final_pass.FINAL_PASS_RESERVE_S


# ── I1: the failure text says only what happened ──────────────────────────


def test_autopilot_failure_text_never_claims_work_that_is_not_running() -> None:
    for detail in (
        "Specialist 'reasoning' timed out after 120.0s",
        "ConnectError: connection refused",
        "something nobody has seen before",
    ):
        msg = _chat_failure_message(detail, autonomy_level=5)
        assert "try again" not in msg.lower(), msg
        assert "continu" not in msg.lower(), msg
        assert "hand" not in msg.lower(), msg

    timeout_msg = _chat_failure_message("Specialist 'reasoning' timed out after 120.0s", autonomy_level=5)
    assert "nothing is running" in timeout_msg.lower(), timeout_msg


def test_below_autopilot_timeout_names_the_turn_limit_not_the_model() -> None:
    msg = _chat_failure_message("Specialist 'reasoning' timed out after 120.0s", autonomy_level=3, turn_timeout_s=140.0)
    assert "the selected model" not in msg.lower(), msg
    assert "140" in msg, msg


@pytest.mark.asyncio
async def test_end_to_end_turn_never_ends_in_a_timeout_message_even_when_both_passes_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _MemoryCoordinatorStub)

    async def _run(autonomy_level: int) -> str:
        brain = OrchestratorBrain(
            config=None,
            llm=None,
            memory_engine=None,
            registry=_Registry({"reasoning": _AlwaysTimesOutSpecialist()}),
        )
        updated = await brain._handle_casual(
            session_id=f"sess-e2e-{autonomy_level}",
            conversation=ConversationManager(),
            prompt="Find and fix the timeout bug.",
            dispatcher=_Dispatcher(),
            mode="auto",
            autonomy_level=autonomy_level,
            token_economy="optimal",
            turn_start=0.0,
        )
        return updated.last_assistant_message()

    autopilot_text = await _run(5)
    assert "try again" not in autopilot_text.lower(), autopilot_text
    assert "the selected model" not in autopilot_text.lower(), autopilot_text

    assisted_text = await _run(3)
    assert "the selected model" not in assisted_text.lower(), assisted_text
    assert "time limit" in assisted_text.lower(), assisted_text


# ── I4: the final pass must not repeat an effectful first-pass action ────


def test_already_acted_recognises_the_real_specialists_task_request_shape() -> None:
    # reasoning.py yields task_request (never tool_result) for a successful
    # send_task, confirmed live against the real specialist
    # (probe_i4_send_task_event_shape.py). record_action_event is what turns
    # that into something already_acted()/send_task_allowed() can see; this
    # pins their read side once it has.
    tool_calls: list[dict[str, object]] = []
    final_pass.record_action_event(tool_calls, {"type": "task_request", "title": "Fix it"})
    assert tool_calls == [{"type": "task_request", "title": "Fix it", "name": "send_task"}]
    assert final_pass.already_acted(tool_calls) is True
    assert final_pass.send_task_allowed(has_send_task=True, autonomy_level=5, tool_calls=tool_calls) is False

    tool_calls = []
    final_pass.record_action_event(tool_calls, {"type": "task_update", "ok": True, "action": "cancel"})
    assert final_pass.already_acted(tool_calls) is True


@pytest.mark.asyncio
async def test_a_timeout_after_a_real_send_task_does_not_create_a_second_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Drives the REAL ReasoningSpecialist (not a fake specialist): the model
    # hands off via send_task, then -- in the SAME pass's batch of tool calls
    # -- asks for a slow read, so the primary pass's own deadline fires AFTER
    # send_task's task_request already reached brain.py, never before it.
    monkeypatch.setattr(final_pass, "FINAL_PASS_RESERVE_S", 0.2)

    class _SlowReadTools:
        def __init__(self) -> None:
            self.reads = 0

        def get(self, name: str) -> SimpleNamespace:
            return SimpleNamespace(name=name)

        async def execute(self, name: str, args: dict) -> SimpleNamespace:
            self.reads += 1
            await asyncio.sleep(1.0)
            return SimpleNamespace(ok=True, data="must never be reached")

    class _SendTaskThenSlowReadLLM:
        model = "gpt-6-sol"

        async def stream_chat(self, messages, tools=None):
            _ = (messages, tools)
            yield _ev("tool_call_end", id="c1", name="send_task", arguments=json.dumps({"title": "Fix it"}))
            yield _ev("tool_call_end", id="c2", name="fs.read_file", arguments=json.dumps({"path": "x.py"}))

    sent: list[dict[str, object]] = []

    async def send_task(**kwargs: object) -> dict[str, object]:
        sent.append(kwargs)
        return {"ok": True}

    tools = _SlowReadTools()
    specialist = ReasoningSpecialist(config=None, llm=_SendTaskThenSlowReadLLM(), tools=tools)
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=_Registry({"reasoning": specialist}))
    brain.runtime_policy = SimpleNamespace(tools=SimpleNamespace(turn_deadline_s=0.3), quality=None, memory=None)

    result = await brain._dispatch_single(
        session_id="sess-i4-real",
        specialist_id="reasoning",
        prompt="Find and fix the timeout bug.",
        conversation=ConversationManager(),
        memory_ctx=MemoryContext(),
        dispatcher=_Dispatcher(),
        thinking=_THINKING_STUB,
        mode="auto",
        autonomy_level=5,
        token_economy="optimal",
        stream_text_events=True,
        send_task=send_task,
    )

    assert len(sent) == 1, "the final pass must not repeat the first pass's real send_task"
    tool_names = [call.get("name") for call in result.tool_calls]
    assert tool_names.count("send_task") == 1
    assert result.status == SpecialistStatus.COMPLETED
    assert result.content.strip()


# ── Requirement 4: a new session inherits the saved default, capped ──────


@pytest.mark.asyncio
async def test_a_new_session_resolves_the_saved_thread_default_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert SessionMeta(session_id="brand-new").autonomy_level is None

    store = SessionStore(tmp_path / "sessions")
    bound = await bind_surface_namespace(store, "sess-fresh", surface_mode="chat", context_id=None)
    assert bound is not None
    _conversation, meta = bound
    assert meta.autonomy_level is None  # not yet the hardcoded 2 the old bug froze on

    db_path = tmp_path / "preferences.sqlite"
    PreferencesStore(str(db_path)).patch(
        PreferencesPatch.model_validate({"autonomy": {"default_level": "L4"}}),
        user_id="default",
        thread_id="sess-fresh",
    )
    monkeypatch.setenv("THOMAS_DB_PATH", str(db_path))
    config = AppConfig(
        models={"local": ModelConfig(name="local", provider="openai_compat", base_url="http://x/v1", model="m")},
        default_model="local",
        tools=ToolsConfig(sandbox_root=str(tmp_path)),
    )
    policy = resolve_chat_runtime_policy(
        payload={}, session_meta=meta, saved_meta=meta, config=config, session_id="sess-fresh"
    )

    # L4 needs a Hello approval it never received, so it runs capped at 3 --
    # never the old hardcoded 2 a freshly-bound session used to freeze on.
    assert policy.autonomy_level == 3


def test_the_web_pages_per_message_level_still_wins_over_any_saved_default() -> None:
    meta = SimpleNamespace(profile="", model_id=None, autonomy_level=None, system_prompt=None)
    policy = resolve_chat_runtime_policy(
        payload={"autonomy_level": 1}, session_meta=meta, saved_meta=meta, config=_local_config(), session_id="sess-web"
    )
    assert policy.autonomy_level == 1


def test_a_never_configured_session_resolves_autonomy_2_not_1(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # _prefs.py's AutonomyPrefs.default_level was "L1": once a fresh session
    # stopped freezing at a hard 2 (above), THIS became the real fallback for
    # a session with no saved preference and no message level -- silently 1,
    # not the default of 2.
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.sqlite"))
    meta = SimpleNamespace(profile="", model_id=None, autonomy_level=None, system_prompt=None)
    policy = resolve_chat_runtime_policy(
        payload={}, session_meta=meta, saved_meta=meta, config=_local_config(), session_id="sess-never-configured"
    )
    assert policy.autonomy_level == 2


# ── Requirement 5: L5 through the preferences schema ─────────────────────


def test_l5_is_legal_in_the_schema_and_resolves_through_the_runtime_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert AutonomyPrefs(default_level="L5").default_level == "L5"

    db_path = tmp_path / "preferences.sqlite"
    PreferencesStore(str(db_path)).patch(
        PreferencesPatch.model_validate({"autonomy": {"default_level": "L5"}}),
        user_id="default",
        thread_id="sess-l5-policy",
    )
    monkeypatch.setenv("THOMAS_DB_PATH", str(db_path))
    meta = SimpleNamespace(profile="", model_id=None, autonomy_level=None, system_prompt=None)
    try:
        policy = resolve_chat_runtime_policy(
            payload={}, session_meta=meta, saved_meta=meta, config=_local_config(), session_id="sess-l5-policy"
        )
        assert policy.autonomy_level == 3  # capped, ungranted
        dial_elevation.approve("autonomy", 5, authorize=lambda *_a: True)
        policy = resolve_chat_runtime_policy(
            payload={}, session_meta=meta, saved_meta=meta, config=_local_config(), session_id="sess-l5-policy"
        )
        assert policy.autonomy_level == 5
    finally:
        dial_elevation.reset_grants()


def test_a_patch_of_l5_round_trips_to_l5_in_stored_preferences(tmp_path: Path) -> None:
    # AutonomyPatch._normalize_autonomy_level used to clamp "L5" to "L4" here,
    # independently of the _types.py schema widening above.
    store = PreferencesStore(str(tmp_path / "preferences.sqlite"))
    store.patch(
        PreferencesPatch.model_validate({"autonomy": {"default_level": "L5"}}),
        user_id="default",
        thread_id="sess-l5",
    )
    assert store.get(user_id="default", thread_id="sess-l5").autonomy.default_level == "L5"


def test_l5_preference_stays_saved_while_the_effective_level_is_capped_without_a_grant(
    tmp_path: Path,
) -> None:
    store = PreferencesStore(str(tmp_path / "preferences.sqlite"))
    store.patch(
        PreferencesPatch.model_validate({"autonomy": {"default_level": "L5"}}),
        user_id="default",
        thread_id="sess-l5-capped",
    )
    # A preference is not a grant: it stays L5 on disk ...
    assert store.get(user_id="default", thread_id="sess-l5-capped").autonomy.default_level == "L5"
    # ... but nothing runs at L5 without a Hello approval -- dial_elevation.cap
    # (already wired through resolve_chat_runtime_policy) decides that.
    try:
        assert dial_elevation.cap("autonomy", 5) == 3
    finally:
        dial_elevation.reset_grants()


def test_the_final_pass_takes_its_link_helper_from_core_not_the_agent_layer():
    """final_pass may not import thomas.agent (the architecture check); the helper lives in core."""
    import ast
    import pathlib

    from thomas.agent import response_tone
    from thomas.core import sandbox_links
    from thomas.marketplace.specialists import final_pass

    tree = ast.parse(pathlib.Path(final_pass.__file__).read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(m == "thomas.agent" or m.startswith("thomas.agent.") for m in modules)
    assert final_pass.strip_sandbox_links is sandbox_links.strip_sandbox_links
    assert response_tone.strip_sandbox_links is sandbox_links.strip_sandbox_links
    assert sandbox_links.strip_sandbox_links("see [the file](sandbox:/mnt/data/x.txt)") == "see the file"
