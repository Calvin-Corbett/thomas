from __future__ import annotations

import asyncio
import contextlib
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
    assert mod._warm_codex_pool_key(cfg)[1] == "gpt-5.4"
    assert mod._is_codex_model_cfg(cfg) is True
    assert mod._is_codex_model_cfg(ModelConfig(name="local", provider="openai_compat", model="dummy")) is False


def test_auto_background_actionable_helper_respects_mode_autonomy_inline_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = SimpleNamespace(action="dispatch")
    monkeypatch.setattr(mod, "should_dispatch", lambda *args, **kwargs: decision)
    assert mod._should_auto_background_actionable("do the task", mode="max", autonomy_level=4) is False
    assert mod._should_auto_background_actionable("do the task", mode="auto", autonomy_level=2) is False
    assert (
        mod._should_auto_background_actionable(
            "do the task", mode="auto", autonomy_level=4, requires_inline_tools=True
        )
        is False
    )
    assert mod._should_auto_background_actionable("do the task", mode="auto", autonomy_level=4) is True

    monkeypatch.setattr(mod, "should_dispatch", lambda *args, **kwargs: SimpleNamespace(action="answer"))
    assert mod._should_auto_background_actionable("do the task", mode="auto", autonomy_level=4) is False


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
    assert codex_provider.config is cfg


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
    monkeypatch.setattr(mod, "_take_warm_codex_provider", lambda app, cfg: None)  # noqa: ARG005

    app = web.Application()
    app[mod.APP_SESSION_LLM_CACHE] = {}
    app[mod.APP_WARM_CODEX_POOL] = {}
    app[mod.APP_WARM_CODEX_TASKS] = {}

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


@pytest.mark.asyncio
async def test_warm_codex_pool_helpers_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    app = web.Application()
    app[mod.APP_WARM_CODEX_POOL] = {}
    app[mod.APP_WARM_CODEX_TASKS] = {}

    non_codex = ModelConfig(name="local", provider="openai_compat", model="dummy")
    mod._schedule_codex_prewarm(app, non_codex)
    assert app[mod.APP_WARM_CODEX_TASKS] == {}
    assert mod._take_warm_codex_provider(app, non_codex) is None

    cfg = ModelConfig(name="codex", provider="codex", model="gpt-5.4")
    scheduled: list[str] = []
    monkeypatch.setattr(mod, "_schedule_codex_prewarm", lambda app_ref, model_cfg: scheduled.append(model_cfg.model))
    pool_key = mod._warm_codex_pool_key(cfg)
    app[mod.APP_WARM_CODEX_POOL][pool_key] = "warm-provider"
    assert mod._take_warm_codex_provider(app, cfg) == "warm-provider"
    assert scheduled == ["gpt-5.4"]

    closed: list[str] = []

    class _ClosableProvider:
        def __init__(self, name: str) -> None:
            self.name = name

        async def close(self) -> None:
            closed.append(self.name)

    async def _task_body() -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(_task_body())
    app[mod.APP_WARM_CODEX_POOL][pool_key] = _ClosableProvider("warm")
    app[mod.APP_WARM_CODEX_TASKS][pool_key] = task
    await mod._cleanup_warm_codex_pool(app)
    assert closed == ["warm"]
    assert task.cancelled() is True


@pytest.mark.asyncio
async def test_schedule_codex_prewarm_handles_existing_entries_and_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    app = web.Application()
    app[mod.APP_WARM_CODEX_POOL] = {}
    app[mod.APP_WARM_CODEX_TASKS] = {}
    cfg = ModelConfig(name="codex", provider="codex", model="gpt-5.4")
    key = mod._warm_codex_pool_key(cfg)

    app[mod.APP_WARM_CODEX_POOL][key] = "existing"
    mod._schedule_codex_prewarm(app, cfg)
    assert app[mod.APP_WARM_CODEX_TASKS] == {}
    app[mod.APP_WARM_CODEX_POOL].clear()

    sleeper = asyncio.create_task(asyncio.sleep(60))
    app[mod.APP_WARM_CODEX_TASKS][key] = sleeper
    mod._schedule_codex_prewarm(app, cfg)
    assert app[mod.APP_WARM_CODEX_TASKS][key] is sleeper
    sleeper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sleeper
    app[mod.APP_WARM_CODEX_TASKS].clear()

    closed: list[str] = []

    class _ClosableProvider:
        async def close(self) -> None:
            closed.append("closed")

    async def _boom(_cfg):  # noqa: ANN001
        raise RuntimeError("warm failed")

    monkeypatch.setattr(mod, "_warm_codex_provider", _boom)
    mod._schedule_codex_prewarm(app, cfg)
    task = app[mod.APP_WARM_CODEX_TASKS][key]
    await task
    assert key not in app[mod.APP_WARM_CODEX_TASKS]
    assert closed == []

    async def _ok(_cfg):  # noqa: ANN001
        return _ClosableProvider()

    monkeypatch.setattr(mod, "_warm_codex_provider", _ok)
    mod._schedule_codex_prewarm(app, cfg)
    task = app[mod.APP_WARM_CODEX_TASKS][key]
    await task
    assert key in app[mod.APP_WARM_CODEX_POOL]
