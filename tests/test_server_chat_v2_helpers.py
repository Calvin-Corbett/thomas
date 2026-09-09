from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from aiohttp import web

from thomas.core.config import ModelConfig
from thomas.server.model_runtime_receipt import sanitize_model_runtime_trace, validate_model_runtime_receipt
from thomas.server.routes import chat_v2 as mod
from thomas.server.routes import chat_v2_request_support as request_support
from thomas.server.routes import chat_v2_support as support


def test_chat_v2_registration_requires_access_guard(tmp_path) -> None:
    with pytest.raises(TypeError, match="require_api_access must be callable"):
        mod.register_chat_v2_routes(
            web.Application(),
            config=SimpleNamespace(),
            llm=None,
            memory=None,
            tools=None,
            chat_store_dir=tmp_path,
            require_api_access=None,
        )


def test_chat_v2_helper_predicates_and_formatters() -> None:
    assert mod._uploaded_audio_format("voice.wave", "") == "wav"
    assert mod._uploaded_audio_format("", "audio/mpeg") == "mp3"
    assert mod._uploaded_audio_format("", "audio/ogg") == "ogg"
    assert mod._uploaded_audio_format("", "audio/webm") == "webm"
    assert mod._uploaded_audio_format("", "audio/mp4") == "m4a"
    assert mod._normalize_reasoning_effort("HIGH") == "high"
    assert mod._normalize_reasoning_effort("none") == "none"
    assert mod._normalize_reasoning_effort("xhigh") == "xhigh"
    assert mod._normalize_reasoning_effort("max") == "max"
    assert mod._normalize_reasoning_effort("weird") == ""
    cfg = ModelConfig(name="codex", provider="codex", model="gpt-5.4", base_url="https://example.test", api_key="k")
    assert mod._llm_signature(cfg)[0] == "codex"


def test_work_display_prompt_contract_is_visible_suffix_only() -> None:
    combined = "[Private Thomas Work onboarding context.]\n\nTriage my customer inbox"
    payload = {"display_prompt": "Triage my customer inbox"}

    assert (
        mod._history_prompt_for_request(
            payload,
            raw_prompt=combined,
            surface_mode="work",
            context_id="mail",
        )
        == "Triage my customer inbox"
    )
    assert (
        mod._history_prompt_for_request(
            {},
            raw_prompt="Visible",
            surface_mode="chat",
            context_id="",
        )
        == "Visible"
    )
    with pytest.raises(ValueError, match="invalid Work display_prompt"):
        mod._history_prompt_for_request(
            payload,
            raw_prompt=combined,
            surface_mode="chat",
            context_id="",
        )
    with pytest.raises(ValueError, match="invalid Work display_prompt"):
        mod._history_prompt_for_request(
            {"display_prompt": "Different text"},
            raw_prompt=combined,
            surface_mode="work",
            context_id="mail",
        )
    with pytest.raises(ValueError, match="invalid Work display_prompt"):
        mod._history_prompt_for_request(
            payload,
            raw_prompt="Untrusted hidden prefix\n\nTriage my customer inbox",
            surface_mode="work",
            context_id="mail",
        )
    with pytest.raises(ValueError, match="invalid Work display_prompt"):
        mod._history_prompt_for_request(
            payload,
            raw_prompt=combined,
            surface_mode="work",
            context_id="mail:triage",
        )


def test_work_connector_tools_bind_only_for_a_resolved_job(monkeypatch: pytest.MonkeyPatch) -> None:
    base = object()
    bound = object()
    calls: list[tuple[object, str]] = []

    def _bind(app: object, tools: object, *, context_id: str) -> object:
        assert tools is base
        calls.append((app, context_id))
        return bound

    app = web.Application()
    monkeypatch.setattr(request_support, "request_work_tools", _bind)

    assert (
        mod._request_tools_for_chat_surface(
            app,
            base,
            surface_mode="work",
            context_id="mail:onboarding:session-1",
            private_context="",
        )
        is base
    )
    assert (
        mod._request_tools_for_chat_surface(
            app,
            base,
            surface_mode="work",
            context_id="mail:owner",
            private_context='{"work_job_id":"owner"}',
        )
        is bound
    )
    assert calls == [(app, "mail:owner")]


def test_work_onboarding_turn_controls_force_a_direct_conversation() -> None:
    assert mod._surface_turn_controls(
        surface_mode="work",
        private_context="",
        mode="max",
        autonomy_level=4,
        token_economy="max",
    ) == ("auto", 2, "optimal")
    assert mod._surface_turn_controls(
        surface_mode="work",
        private_context='{"work_job_id":"owner"}',
        mode="max",
        autonomy_level=4,
        token_economy="max",
    ) == ("max", 4, "max")


def test_model_runtime_receipt_is_observed_and_secret_safe() -> None:
    class _ObservedLLM:
        def runtime_trace(self):  # noqa: ANN201
            return {
                "requested": {
                    "profile": "openai_codex",
                    "provider": "openai_codex",
                    "model": "gpt-5.6-sol",
                    "api_key": "must-not-leak",
                },
                "active": {
                    "profile": "openai_codex",
                    "provider": "openai_codex",
                    "model": "gpt-5.6-sol",
                    "access_token": "must-not-leak",
                },
                "failover_enabled": True,
                "failover_used": False,
                "attempts": [
                    {
                        "profile": "openai_codex",
                        "provider": "openai_codex",
                        "model": "gpt-5.6-sol",
                        "status": "success",
                        "error": "sensitive provider detail",
                    }
                ],
            }

    receipt = mod.model_runtime_receipt(
        _ObservedLLM(), requested_profile="openai_codex", requested_model_id="gpt-5.6-sol"
    )

    assert receipt["active"]["model"] == "gpt-5.6-sol"
    assert receipt["attempts"] == [
        {
            "profile": "openai_codex",
            "provider": "openai_codex",
            "model": "gpt-5.6-sol",
            "status": "success",
        }
    ]
    assert "must-not-leak" not in json.dumps(receipt)
    assert "sensitive provider detail" not in json.dumps(receipt)


def test_model_runtime_receipt_surfaces_trace_failure(caplog: pytest.LogCaptureFixture) -> None:
    class _BrokenLLM:
        _failover_enabled = True

        def runtime_trace(self):  # noqa: ANN201
            raise RuntimeError("sk-secret-in-exception")

    receipt = mod.model_runtime_receipt(_BrokenLLM(), requested_profile="local", requested_model_id="qwen")

    assert receipt["trace_error"] == "runtime_trace_failed"
    assert receipt["active"] == {}
    assert "Model runtime trace failed at the telemetry boundary" in caplog.text
    assert "sk-secret-in-exception" not in caplog.text


def test_model_runtime_receipt_validation_rejects_stale_or_mismatched_proof() -> None:
    valid = {
        "requested": {"profile": "chatgpt", "provider": "openai", "model": "gpt-5.6-sol"},
        "active": {"profile": "chatgpt", "provider": "openai", "model": "gpt-5.6-sol"},
        "attempts": [
            {
                "profile": "chatgpt",
                "provider": "openai",
                "model": "gpt-5.6-sol",
                "status": "success",
            }
        ],
    }
    assert validate_model_runtime_receipt(valid, requested_profile="chatgpt", requested_model_id="gpt-5.6-sol")
    assert validate_model_runtime_receipt({**valid, "attempts": []}) is None
    assert validate_model_runtime_receipt({**valid, "trace_error": "sk-secret-token"}) is None
    assert validate_model_runtime_receipt(valid, requested_profile="chatgpt", requested_model_id="other-model") is None
    sanitized = sanitize_model_runtime_trace({**valid, "trace_error": "sk-secret-token"})
    assert sanitized["trace_error"] == "runtime_trace_failed"
    assert "sk-secret-token" not in json.dumps(sanitized)


def test_announcement_lock_reuses_session_llm_lock_and_fallback() -> None:
    app = web.Application()
    cached = asyncio.Lock()
    app[mod.APP_SESSION_LLM_CACHE] = {"cached": SimpleNamespace(lock=cached)}
    app[mod.APP_ANNOUNCE_LOCKS] = {}
    assert mod._announcement_lock_for(app, "cached") is cached

    fallback = mod._announcement_lock_for(app, "other")
    assert mod._announcement_lock_for(app, "other") is fallback
    assert mod._UNSUPPORTED_GAP_CLAIM_RE.search("report.html is ready; the other item still needs to be created")
    assert mod._UNSUPPORTED_GAP_CLAIM_RE.search("report.html is ready; the remaining task is pending")
    for claim in (
        "the recipe isn't ready",
        "I didn't finish the recipe",
        "the recipe is still pending",
        "the recipe has yet to land",
        "The chart is forthcoming",
        "The rest will follow shortly",
    ):
        assert mod._UNSUPPORTED_GAP_CLAIM_RE.search(claim), claim


def test_privacy_controls_parse_aliases_and_fail_closed() -> None:
    assert mod._resolve_privacy_controls({}) == (False, True)
    assert mod._resolve_privacy_controls({"temporary_chat": "yes"}) == (True, True)
    assert mod._resolve_privacy_controls({"temporary": True, "network_access": "off"}) == (True, False)
    assert mod._resolve_privacy_controls({"external_access": True, "allow_network": False}) == (False, False)
    assert mod._is_external_tool_name("browser.open") is True
    assert mod._is_external_tool_name("functions.email.send") is True
    assert mod._is_external_tool_name("mcp__web.search") is True
    assert mod._is_external_tool_name("fs.read") is False


@pytest.mark.asyncio
async def test_privacy_restricted_tools_never_execute_external_tools() -> None:
    from thomas.tools.base import ToolResult

    external = SimpleNamespace(name="browser.open", category="network")
    local = SimpleNamespace(name="fs.read", category="files")

    class _FakeTools:
        def __init__(self) -> None:
            self.executed: list[str] = []

        def get(self, name: str):  # noqa: ANN201
            return {"browser.open": external, "fs.read": local}.get(name)

        def list_tools(self, category=None):  # noqa: ANN001, ANN201
            rows = [external, local]
            return [tool for tool in rows if category is None or tool.category == category]

        def search(self, query: str, limit: int = 10):  # noqa: ANN201
            del query
            return [external, local][:limit]

        async def execute(self, name: str, args: dict):  # noqa: ANN001, ANN201
            del args
            self.executed.append(name)
            return ToolResult(ok=True, data={"tool": name})

        def __contains__(self, name: str) -> bool:
            return name in {"browser.open", "fs.read"}

    base = _FakeTools()
    restricted = mod._PrivacyRestrictedTools(base)

    denied = await restricted.execute("browser.open", {"url": "https://example.test"})
    allowed = await restricted.execute("fs.read", {"path": "README.md"})

    assert denied.ok is False
    assert "External access is disabled" in str(denied.error)
    assert restricted.denied == ["browser.open"]
    assert base.executed == ["fs.read"]
    assert allowed.ok is True
    assert restricted.get("browser.open") is None
    assert restricted.get("fs.read") is local
    assert [tool.name for tool in restricted.list_tools()] == ["fs.read"]
    assert [tool.name for tool in restricted.search("anything")] == ["fs.read"]
    assert "browser.open" not in restricted
    assert "fs.read" in restricted


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
    # A session may only flag its own existing delegation; unknown and ownerless
    # rows fail closed so one chat cannot suppress another chat's completion.
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

    # Unknown row -> 404 and never marked.
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: None)
    resp = await mod.handle_mark_delegation_reported(_req("sess-2", "exec-10"))
    assert resp.status == 404
    assert "exec-10" not in marked

    # Ownerless legacy row -> 403 and never marked.
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: {"conversation_id": ""})
    resp = await mod.handle_mark_delegation_reported(_req("sess-2", "exec-11"))
    assert resp.status == 403
    assert "exec-11" not in marked


@pytest.mark.asyncio
async def test_cancel_delegation_uses_session_scoped_task_update(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp.test_utils import make_mocked_request

    calls: list[tuple[str, str, bool]] = []

    def _cancel(sid: str, eid: str, update: str = "", *, cancel: bool = False):
        calls.append((sid, eid, cancel))
        if sid == "sess-1" and eid == "exec-9":
            return {"ok": True, "execution_id": eid, "action": "cancel"}
        return {"ok": False, "error": "No running task matches reference."}

    monkeypatch.setattr(request_support, "apply_task_update", _cancel)

    request = make_mocked_request("POST", "/x", match_info={"session_id": "sess-1", "execution_id": "exec-9"})
    response = await mod.handle_cancel_delegation(request)
    assert response.status == 200
    assert calls == [("sess-1", "exec-9", True)]

    missing = make_mocked_request("POST", "/x", match_info={"session_id": "other", "execution_id": "exec-9"})
    response = await mod.handle_cancel_delegation(missing)
    assert response.status == 404


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

    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "missing",
        },
    )
    resp = await mod.handle_announce_delegation(_req("sess-1", "exec-9"))
    assert resp.status == 200
    assert resp.text is not None
    assert "unverified_completion" in resp.text

    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "verified",
            "runtime_profile": {"canvas": True},
            "proof": {"status": "verified", "artifacts": []},
        },
    )
    resp = await mod.handle_announce_delegation(_req("sess-1", "exec-9"))
    assert resp.status == 200
    assert resp.text is not None
    assert "canvas_without_verified_artifact" in resp.text


@pytest.mark.asyncio
async def test_announce_delegation_strips_sandbox_links_from_note(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    class _FakeLLM:
        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            async def _events():
                yield SimpleNamespace(
                    type="token",
                    data={"text": "Done - your chart is ready: [download chart.png](sandbox:/mnt/data/chart.png)."},
                )

            return _events()

    class _FakeStore:
        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "make a png chart")
            self.saved = None

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.saved = (sid, conversation, meta, force)

    app = web.Application()
    store = _FakeStore()
    app[mod.APP_SESSION_STORE] = store
    app[mod.APP_SESSION_LLM_CACHE] = {"sess-1": SimpleNamespace(llm=_FakeLLM())}
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": [{"kind": "image", "path": "chart.png"}]},
            "progress_summary": "Rendered the chart",
            "bot_name": "Canvas Worker",
        },
    )
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: None)
    req = make_mocked_request("POST", "/x", match_info={"session_id": "sess-1", "execution_id": "exec-9"}, app=app)
    resp = await mod.handle_announce_delegation(req)

    assert resp.status == 200
    assert resp.text is not None
    # The broken sandbox link is gone; the label and file name survive.
    assert "sandbox:" not in resp.text
    assert "](" not in resp.text
    assert "chart.png" in resp.text
    last = store.saved[1].last_assistant_message()
    assert "sandbox:" not in last
    assert last == "Done - your chart is ready: download chart.png."


@pytest.mark.asyncio
async def test_announce_device_action_with_script_and_docs_flags_built_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    captured: dict = {}

    class _FakeLLM:
        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            captured["messages"] = kwargs.get("messages") or list(args)

            async def _events():
                yield SimpleNamespace(
                    type="token",
                    data={
                        "text": (
                            "I built a control for it: SETUP.md, kitchen-lights.ps1, and SETUP.pdf are "
                            "ready — connect your hub to run it."
                        )
                    },
                )

            return _events()

    class _FakeStore:
        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "turn off my kitchen lights")
            self.saved = None

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.saved = (sid, conversation, meta, force)

    app = web.Application()
    app[mod.APP_SESSION_STORE] = _FakeStore()
    app[mod.APP_SESSION_LLM_CACHE] = {"sess-1": SimpleNamespace(llm=_FakeLLM())}
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "verified",
            "proof": {
                "status": "verified",
                "artifacts": [
                    {"kind": "doc", "path": "SETUP.md"},
                    {"kind": "script", "path": "kitchen-lights.ps1"},
                    {"kind": "doc", "path": "SETUP.pdf"},
                ],
            },
            "summary": "turn off my kitchen lights",
            "bot_name": "Bridge Worker",
        },
    )
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: None)
    req = make_mocked_request("POST", "/x", match_info={"session_id": "sess-1", "execution_id": "exec-9"}, app=app)
    resp = await mod.handle_announce_delegation(req)

    assert resp.status == 200
    # The bridge honesty instruction must fire even though SETUP.md/SETUP.pdf are
    # not scripts — a .ps1 control script means the physical action did NOT happen.
    user_prompt = " ".join(str(m.get("content", "")) for m in (captured.get("messages") or []) if isinstance(m, dict))
    assert "physical action has NOT been performed" in user_prompt
    assert "NEVER say the action happened" in user_prompt


@pytest.mark.asyncio
async def test_announce_delegation_persists_model_note_and_marks_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    class _FakeLLM:
        prompts: list[str] = []

        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.prompts.append(str(kwargs.get("messages") or args))

            async def _events():
                yield SimpleNamespace(type="token", data={"text": "All set - report.html is ready."})

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
            "execution_id": eid,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": [{"kind": "web", "path": "report.html"}]},
            "progress_summary": "Wrote the report",
            "bot_name": "Report Worker",
        },
    )
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: updates.append((eid, kw)))
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
    assert "report.html" in resp.text
    # The prompt still hands the model the complete artifact list; only the
    # wording moved. 904c07bc ("Verified means what was checked") stopped the
    # prompt from calling a render-only artifact list a verified one, and
    # test_a_render_only_check_is_not_announced_as_bare_verified.py now guards
    # that the old wording never returns. What is asserted here is unchanged:
    # the model is told every artifact by name.
    assert _FakeLLM.prompts and "complete list of files it produced is: report.html" in _FakeLLM.prompts[0]
    assert store.saved is not None
    saved_sid, saved_conversation, _meta, force = store.saved
    assert saved_sid == "sess-1"
    assert force is True
    last = saved_conversation.last_assistant_message()
    assert last == "All set - report.html is ready."
    assert updates and updates[0][0] == "exec-9"
    assert "reported_to_chat_at" in updates[0][1]


@pytest.mark.asyncio
async def test_announce_delegation_presents_exact_max_verified_answer_without_rewriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    answer = "# Audited decision\n\nChat wins 94/100.\n\nMAX_VERIFIED_ANSWER"

    class _FakeStore:
        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("assistant", "Max review is running.")
            self.saved = None

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.saved = (sid, conversation, meta, force)

    app = web.Application()
    store = _FakeStore()
    app[mod.APP_SESSION_STORE] = store
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-max-answer",
            "state": "completed",
            "proof_status": "verified",
            "runtime_profile": {
                "max_answer_only": True,
                "max_verified_answer_text": answer,
            },
            "progress_summary": "Audited decision ready.",
            "bot_name": "Max crew",
        },
    )
    updates: list[tuple[str, dict]] = []
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: updates.append((eid, kw)))
    req = make_mocked_request(
        "POST",
        "/x",
        match_info={"session_id": "sess-max-answer", "execution_id": "exec-max-answer"},
        app=app,
    )

    resp = await mod.handle_announce_delegation(req)

    assert resp.status == 200
    assert json.loads(resp.text)["message"] == answer
    assert store.saved is not None
    assert store.saved[1].last_assistant_message() == answer
    assert updates and "reported_to_chat_at" in updates[0][1]


@pytest.mark.asyncio
async def test_announce_delegation_presents_verified_text_deliverable_without_rewriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    answer = (
        "## Eight-step QA plan\n\n"
        "1. Start a long Chat task.\n"
        "2. Switch to Code while Chat is running.\n"
        "3. Return and verify the exact final marker.\n\n"
        "CHAT_SWITCH_SURVIVED_0718"
    )

    class _NoRewriteLLM:
        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("verified text deliverable must not be rewritten")

    class _FakeStore:
        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "Give me an eight-step QA plan.")
            self.saved = None

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.saved = (sid, conversation, meta, force)

    app = web.Application()
    store = _FakeStore()
    app[mod.APP_SESSION_STORE] = store
    app[mod.APP_SESSION_LLM_CACHE] = {"sess-text": SimpleNamespace(llm=_NoRewriteLLM())}
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-text",
            "state": "completed",
            "summary": "Give me an eight-step QA plan.",
            "progress_summary": answer,
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": []},
            "bot_name": "Zach",
        },
    )
    updates: list[tuple[str, dict]] = []
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: updates.append((eid, kw)))
    request = make_mocked_request(
        "POST",
        "/x",
        match_info={"session_id": "sess-text", "execution_id": "exec-text"},
        app=app,
    )

    response = await mod.handle_announce_delegation(request)

    assert response.status == 200
    assert json.loads(response.text)["message"] == answer
    assert store.saved is not None
    assert store.saved[1].last_assistant_message() == answer
    assert updates and "reported_to_chat_at" in updates[0][1]


@pytest.mark.asyncio
async def test_announce_delegation_never_echoes_task_title_as_verified_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    class _FakeStore:
        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "Give me an eight-step plan.")
            self.saved = None

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.saved = (sid, conversation, meta, force)

    app = web.Application()
    store = _FakeStore()
    app[mod.APP_SESSION_STORE] = store
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-missing-text",
            "state": "completed",
            "summary": "Give me an eight-step plan.",
            "progress_summary": "",
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": []},
        },
    )
    monkeypatch.setattr(
        task_bot_runtime,
        "update_execution",
        lambda *args, **kwargs: pytest.fail("missing text must not be marked reported"),
    )
    request = make_mocked_request(
        "POST",
        "/x",
        match_info={"session_id": "sess-missing-text", "execution_id": "exec-missing-text"},
        app=app,
    )

    response = await mod.handle_announce_delegation(request)

    assert response.status == 200
    assert json.loads(response.text) == {"ok": True, "skipped": "verified_text_missing"}
    assert store.saved is None


@pytest.mark.asyncio
async def test_parallel_announcements_serialize_llm_and_preserve_both_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    class _GuardedLLM:
        active = 0
        max_active = 0

        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            async def _events():
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                await asyncio.sleep(0.01)
                yield SimpleNamespace(type="token", data={"text": "A verified result is ready."})
                self.active -= 1

            return _events()

    class _Store:
        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "Make both files.")

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.loaded = conversation

    app = web.Application()
    llm = _GuardedLLM()
    store = _Store()
    app[mod.APP_SESSION_STORE] = store
    app[mod.APP_ANNOUNCE_LOCKS] = {}
    app[mod.APP_SESSION_LLM_CACHE] = {
        "sess-1": SimpleNamespace(llm=llm, lock=asyncio.Lock()),
    }
    rows = {
        exec_id: {
            "execution_id": exec_id,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": [{"kind": "text", "path": f"{exec_id}.md"}]},
            "summary": f"Build {exec_id}",
        }
        for exec_id in ("one", "two")
    }
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: rows[eid])

    def _updated(eid, **kwargs):  # noqa: ANN001, ANN202
        rows[eid].update(kwargs)

    monkeypatch.setattr(task_bot_runtime, "update_execution", _updated)

    def _req(exec_id: str):
        return make_mocked_request(
            "POST",
            "/x",
            match_info={"session_id": "sess-1", "execution_id": exec_id},
            app=app,
        )

    responses = await asyncio.gather(
        mod.handle_announce_delegation(_req("one")),
        mod.handle_announce_delegation(_req("two")),
    )
    assert all(response.status == 200 for response in responses)
    assert llm.max_active == 1
    assistants = [
        row for row in store.loaded.get_context_window(max_tokens=2000) if str(row.get("role")) == "assistant"
    ]
    assert len(assistants) == 2


@pytest.mark.asyncio
async def test_session_llm_cache_replacement_and_cleanup_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[str] = []

    class _FakeLLM:
        def __init__(self, config, fallback_configs=None, failover_enabled=False, **kwargs):  # noqa: ANN001
            self.config = config
            self._primary_config = config
            self._fallback_configs = list(fallback_configs or [])
            self._failover_enabled = bool(failover_enabled)
            self._codex_provider = None
            self._failover_cooldown_s = int(kwargs.get("failover_cooldown_s", 300))
            self._failover_on_auth_error = bool(kwargs.get("failover_on_auth_error", False))
            self._max_retries = int(kwargs.get("max_retries", 3))
            self._base_retry_delay = float(kwargs.get("base_retry_delay_s", 0.8))
            self._request_overrides = dict(kwargs.get("request_overrides") or {})

        async def close(self) -> None:
            closed.append(str(getattr(self.config, "model", "")))

    monkeypatch.setattr(mod, "LLMClient", _FakeLLM)

    app = web.Application()
    app[mod.APP_SESSION_LLM_CACHE] = {}

    cfg1 = ModelConfig(name="primary", provider="openai_compat", model="gpt-4o")
    llm1, lock1 = await support._get_or_create_session_llm(
        app,
        session_id="sess-1",
        model_cfg=cfg1,
        fallback_cfgs=[],
        failover_enabled=False,
    )
    cfg2 = replace(cfg1, api_key="changed")
    llm2, lock2 = await support._get_or_create_session_llm(
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
async def test_session_export_and_delete_return_verifiable_receipts() -> None:
    from aiohttp.test_utils import make_mocked_request

    conversation = mod.ConversationManager().append_message("user", "export marker")
    meta = mod.SessionMeta(session_id="sess-private", profile="openai_codex", model_id="gpt-5.6-sol")

    class _FakeStore:
        def __init__(self) -> None:
            self.present = True
            self.deleted: list[str] = []

        async def load(self, sid: str):  # noqa: ANN201
            return conversation if self.present and sid == "sess-private" else None

        async def load_meta(self, sid: str):  # noqa: ANN201
            return meta if self.present and sid == "sess-private" else None

        async def delete(self, sid: str) -> bool:
            self.deleted.append(sid)
            was_present = self.present
            self.present = False
            return was_present

    class _FakeMemory:
        def __init__(self) -> None:
            self.forgotten: list[str] = []

        def forget_thread(self, sid: str) -> dict:
            self.forgotten.append(sid)
            return {"forgotten": True, "thread_id": sid, "deleted_rows": 3}

    class _FakeLLM:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    app = web.Application()
    store = _FakeStore()
    memory = _FakeMemory()
    llm = _FakeLLM()
    app[mod.APP_SESSION_STORE] = store
    app[mod.APP_SESSION_LLM_CACHE] = {
        "sess-private": mod._CachedSessionLLM(llm=llm, signature=("", "", "", "", ""), lock=asyncio.Lock())
    }
    if mod.APP_MEMORY is not None:
        app[mod.APP_MEMORY] = memory

    export_request = make_mocked_request(
        "GET",
        "/api/v2/chat/session/sess-private/export",
        match_info={"session_id": "sess-private"},
        app=app,
    )
    export_response = await mod.handle_session_export(export_request)
    export_payload = json.loads(export_response.text)
    assert export_response.status == 200
    assert export_response.headers["Content-Disposition"] == 'attachment; filename="thomas-chat-sess-private.json"'
    assert export_payload["schema_version"] == "thomas.chat.export.v1"
    assert export_payload["session_id"] == "sess-private"
    assert export_payload["conversation"]["messages"][0]["content"] == "export marker"
    assert export_payload["meta"]["model_id"] == "gpt-5.6-sol"

    delete_request = make_mocked_request(
        "DELETE",
        "/api/v2/chat/session/sess-private",
        match_info={"session_id": "sess-private"},
        app=app,
    )
    delete_response = await mod.handle_session_delete(delete_request)
    delete_payload = json.loads(delete_response.text)
    # Exact equality on purpose. A deletion receipt is a claim about what was
    # destroyed, so an unexpected field means the claim changed shape and should
    # be read before it is accepted -- which is exactly how this caught up with
    # `task_records_removed` being added when deleting a chat began deleting the
    # task records behind it too. Zero here because this session ran no tasks.
    assert delete_payload == {
        "deleted": True,
        "session_id": "sess-private",
        "memory_purge": {
            "completed": True,
            "forgotten": True,
            "thread_id": "sess-private",
            "deleted_rows": 3,
        },
        "task_records_removed": 0,
    }
    assert store.deleted == ["sess-private"]
    assert memory.forgotten == ["sess-private"]
    assert llm.closed is True
    assert "sess-private" not in app[mod.APP_SESSION_LLM_CACHE]

    missing_response = await mod.handle_session_export(export_request)
    assert missing_response.status == 404
