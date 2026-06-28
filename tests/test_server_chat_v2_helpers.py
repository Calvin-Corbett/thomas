from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from aiohttp import web

from thomas.core.config import ModelConfig
from thomas.server.routes import chat_v2 as mod


def test_chat_v2_helper_predicates_and_formatters() -> None:
    assert mod._requests_reply_first_background("Reply now and do the rest in the background") is True
    assert mod._requests_reply_first_background("just answer this") is False

    assert mod._requests_explicit_delegation("Spawn exactly three real sub-agents now") is True
    assert mod._requests_explicit_delegation("just think about it") is False

    assert mod._requires_inline_tool_execution("Use your file tools and name three top-level files") is True
    assert mod._requires_inline_tool_execution("hello there") is False

    constrained = mod._foreground_reply_prompt("Answer now, then in the background draft a plan.")
    assert "[Visible reply constraint]" in constrained
    assert "draft a plan" not in constrained.split("[Visible reply constraint]")[0]

    assert mod._uploaded_audio_format("voice.wave", "") == "wav"
    assert mod._uploaded_audio_format("", "audio/mpeg") == "mp3"
    assert mod._uploaded_audio_format("", "audio/ogg") == "ogg"
    assert mod._uploaded_audio_format("", "audio/webm") == "webm"
    assert mod._uploaded_audio_format("", "audio/mp4") == "m4a"
    assert mod._normalize_reasoning_effort("HIGH") == "high"
    assert mod._normalize_reasoning_effort("weird") == ""
    cfg = ModelConfig(name="codex", provider="codex", model="gpt-5.4", base_url="https://example.test", api_key="k")
    assert mod._llm_signature(cfg)[0] == "codex"


def test_auto_background_actionable_helper_respects_mode_autonomy_inline_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = SimpleNamespace(action="dispatch")
    monkeypatch.setattr(mod, "should_dispatch", lambda *args, **kwargs: decision)
    assert mod._should_auto_background_actionable("do the task", mode="max", autonomy_level=4) is False
    assert mod._should_auto_background_actionable("do the task", mode="auto", autonomy_level=2) is False
    assert (
        mod._should_auto_background_actionable("do the task", mode="auto", autonomy_level=4, requires_inline_tools=True)
        is False
    )
    assert mod._should_auto_background_actionable("do the task", mode="auto", autonomy_level=4) is True

    monkeypatch.setattr(mod, "should_dispatch", lambda *args, **kwargs: SimpleNamespace(action="answer"))
    assert mod._should_auto_background_actionable("do the task", mode="auto", autonomy_level=4) is False


def test_auto_background_actionable_keeps_memory_prompt_inline() -> None:
    prompt = "Memory smoke test: remember that the temporary code phrase is BLUE CEDAR 936. Reply with exactly: stored"
    assert mod._should_auto_background_actionable(prompt, mode="auto", autonomy_level=4) is False


@pytest.mark.asyncio
async def test_voice_bridge_request_refresh_and_cached_llm_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeVoiceBridge:
        pass

    monkeypatch.setattr(mod, "VoiceBridge", _FakeVoiceBridge)
    app = web.Application()

    bridge = await mod._voice_bridge_for_request(app)
    again = await mod._voice_bridge_for_request(app)
    assert isinstance(bridge, _FakeVoiceBridge)
    assert again is bridge

    codex_provider = SimpleNamespace(config=None)
    llm = SimpleNamespace(
        config=None,
        _primary_config=None,
        _fallback_configs=None,
        _failover_enabled=None,
        _codex_provider=codex_provider,
    )
    cfg = ModelConfig(name="primary", provider="codex", model="gpt-5.4", reasoning_effort="medium")
    updated = mod._refresh_cached_llm(
        mod._CachedSessionLLM(llm=llm, signature=mod._llm_signature(cfg), lock=asyncio.Lock()),
        model_cfg=cfg,
        fallback_cfgs=[replace(cfg, model="fallback")],
        failover_enabled=True,
    )
    assert updated.config is cfg
    assert updated._primary_config is cfg
    assert len(updated._fallback_configs) == 1
    assert updated._failover_enabled is True


@pytest.mark.asyncio
async def test_mark_delegation_reported_is_session_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    # Round-4 eventflow nit: a session may only flag its OWN delegations; fail OPEN for
    # unknown rows so the common path is never broken.
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    marked: list[str] = []
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: marked.append(eid))

    def _req(sid: str, eid: str):
        return make_mocked_request("POST", "/x", match_info={"session_id": sid, "execution_id": eid})

    # Row owned by a DIFFERENT conversation -> 403, not marked.
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: {"conversation_id": "other-sess"})
    resp = await mod.handle_mark_delegation_reported(_req("sess-1", "exec-9"))
    assert resp.status == 403
    assert marked == []

    # Row owned by THIS conversation -> marked.
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: {"conversation_id": "sess-1"})
    resp = await mod.handle_mark_delegation_reported(_req("sess-1", "exec-9"))
    assert resp.status == 200
    assert marked == ["exec-9"]

    # Unknown row (no conversation id) -> fail OPEN, marked.
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: None)
    resp = await mod.handle_mark_delegation_reported(_req("sess-2", "exec-10"))
    assert resp.status == 200
    assert "exec-10" in marked


@pytest.mark.asyncio
async def test_announce_delegation_skips_already_reported_or_non_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    def _req(sid: str, eid: str):
        return make_mocked_request("POST", "/x", match_info={"session_id": sid, "execution_id": eid})

    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {"conversation_id": "sess-1", "reported_to_chat_at": "2026-06-17T00:00:00Z"},
    )
    resp = await mod.handle_announce_delegation(_req("sess-1", "exec-9"))
    assert resp.status == 200
    assert resp.text is not None
    assert "already_reported" in resp.text

    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {"conversation_id": "sess-1", "state": "running"},
    )
    resp = await mod.handle_announce_delegation(_req("sess-1", "exec-9"))
    assert resp.status == 200
    assert resp.text is not None
    assert "not_terminal" in resp.text


@pytest.mark.asyncio
async def test_announce_delegation_persists_model_note_and_marks_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime
    from thomas.server.routes import deliverable_aiohttp

    class _FakeLLM:
        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            async def _events():
                yield SimpleNamespace(type="token", data={"text": "All set - I have the report ready."})

            return _events()

    class _FakeStore:
        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "Please make the report.")
            self.saved = None

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.saved = (sid, conversation, meta, force)

    app = web.Application()
    store = _FakeStore()
    app[mod.APP_SESSION_STORE] = store
    app[mod.APP_SESSION_LLM_CACHE] = {"sess-1": SimpleNamespace(llm=_FakeLLM())}

    updates: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "conversation_id": "sess-1",
            "state": "completed",
            "progress_summary": "Wrote the report",
            "bot_name": "Report Worker",
        },
    )
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: updates.append((eid, kw)))
    monkeypatch.setattr(deliverable_aiohttp, "deliverable_entry", lambda eid: "/deliverables/report.html")

    req = make_mocked_request(
        "POST",
        "/x",
        match_info={"session_id": "sess-1", "execution_id": "exec-9"},
        app=app,
    )
    resp = await mod.handle_announce_delegation(req)

    assert resp.status == 200
    assert resp.text is not None
    assert "All set" in resp.text
    assert store.saved is not None
    saved_sid, saved_conversation, _meta, force = store.saved
    assert saved_sid == "sess-1"
    assert force is True
    last = saved_conversation.last_assistant_message()
    assert last == "All set - I have the report ready."
    assert updates and updates[0][0] == "exec-9"
    assert "reported_to_chat_at" in updates[0][1]


@pytest.mark.asyncio
async def test_session_llm_cache_replacement_and_cleanup_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[str] = []

    class _FakeLLM:
        def __init__(self, config, fallback_configs=None, failover_enabled=False):  # noqa: ANN001
            self.config = config
            self._primary_config = config
            self._fallback_configs = list(fallback_configs or [])
            self._failover_enabled = bool(failover_enabled)
            self._codex_provider = None

        async def close(self) -> None:
            closed.append(str(getattr(self.config, "model", "")))

    monkeypatch.setattr(mod, "LLMClient", _FakeLLM)

    app = web.Application()
    app[mod.APP_SESSION_LLM_CACHE] = {}

    cfg1 = ModelConfig(name="primary", provider="openai_compat", model="gpt-4o")
    llm1, lock1 = await mod._get_or_create_session_llm(
        app,
        session_id="sess-1",
        model_cfg=cfg1,
        fallback_cfgs=[],
        failover_enabled=False,
    )
    cfg2 = replace(cfg1, api_key="changed")
    llm2, lock2 = await mod._get_or_create_session_llm(
        app,
        session_id="sess-1",
        model_cfg=cfg2,
        fallback_cfgs=[],
        failover_enabled=False,
    )
    assert llm1 is not llm2
    assert lock1 is lock2
    assert closed == ["gpt-4o"]

    await mod._evict_session_llm(app, "sess-1")
    assert len(closed) == 2
    await mod._evict_session_llm(app, "missing")

    app[mod.APP_SESSION_LLM_CACHE]["sess-2"] = mod._CachedSessionLLM(
        llm=_FakeLLM(cfg1),
        signature=mod._llm_signature(cfg1),
        lock=asyncio.Lock(),
    )
    await mod._cleanup_cached_session_llms(app)
    assert len(closed) == 3
