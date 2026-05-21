import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.routes import chat_v2 as chat_v2_routes
from thomas.tools.voice import VoiceProviderException


def _parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class _FakeBrain:
    calls = []

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        payload = dict(kwargs or {})
        payload["prompt"] = prompt
        _FakeBrain.calls.append(payload)
        updated = conversation.append_message("user", prompt)
        reply = "Thomas reply."
        await dispatcher.emit_text(reply)
        updated = updated.append_message(
            "assistant", reply, metadata={"specialists": ["reasoning"], "mode": "conversation"}
        )
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=updated.version,
            thinking_summary="conversation",
            total_thinking_ms=0,
            iterations=1,
            tool_calls=0,
            tokens_used=0,
            specialists_used=["reasoning"],
        )
        return updated


class _FakeLLMClient:
    calls = []
    closed = []

    def __init__(self, config, fallback_configs=None, failover_enabled=False):  # noqa: ANN001
        self.config = config
        self._primary_config = config
        self._fallback_configs = list(fallback_configs or [])
        self._failover_enabled = bool(failover_enabled)
        self._codex_provider = None
        _FakeLLMClient.calls.append(
            {
                "reasoning_effort": getattr(config, "reasoning_effort", ""),
                "model": getattr(config, "model", ""),
                "failover_enabled": bool(failover_enabled),
                "fallback_count": len(list(fallback_configs or [])),
            }
        )

    async def close(self):
        _FakeLLMClient.closed.append(
            {
                "reasoning_effort": getattr(self.config, "reasoning_effort", ""),
                "model": getattr(self.config, "model", ""),
            }
        )


class _FakeDelegationStarter:
    calls = []

    @staticmethod
    async def start(app, *, session_id, prompt, mode, recent_messages, emit_event, repo_root=None, force=False):  # noqa: ANN001
        _ = app
        _ = repo_root
        _ = force
        _FakeDelegationStarter.calls.append(
            {
                "session_id": session_id,
                "prompt": prompt,
                "mode": mode,
                "recent_messages": list(recent_messages or []),
            }
        )
        await emit_event(
            {
                "type": "delegation_started",
                "execution_id": "exec-123",
                "task_id": "task-123",
                "session_id": session_id,
                "backend_type": "task_manager",
                "state": "queued",
                "summary": prompt,
                "last_progress": "Queued for background execution.",
                "specialist_id": "coding",
                "bot_id": "nova",
                "bot_name": "Nova",
                "bot_color": "#4fc3f7",
                "bot_costume": "cap",
                "bot_tint": "blue",
            }
        )
        return {"execution_id": "exec-123"}


class _FakeVoiceBridge:
    calls = []

    async def transcribe(self, audio):  # noqa: ANN001
        _FakeVoiceBridge.calls.append(
            {
                "format": getattr(audio, "format", ""),
                "bytes": len(getattr(audio, "data", b"")),
            }
        )
        return "hello from mic"


class _VoiceProviderBoom:
    async def transcribe(self, audio):  # noqa: ANN001
        _ = audio
        raise VoiceProviderException("voice offline")


class _VoiceGenericBoom:
    async def transcribe(self, audio):  # noqa: ANN001
        _ = audio
        raise RuntimeError("decoder crashed")


class _FakeBrainBoom:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        _ = session_id, conversation, prompt, dispatcher, kwargs
        raise RuntimeError("brain exploded")


class TestServerChatV2MaxMode(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={
                "local": ModelConfig(
                    name="local",
                    provider="openai_compat",
                    base_url="http://127.0.0.1:11434/v1",
                    model="dummy",
                )
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_max_mode_streams_thomas_reply_and_background_delegation(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-max",
                    "profile": "local",
                    "mode": "max",
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        self.assertIn("application/x-ndjson", str(resp.headers.get("Content-Type") or ""))

        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertIn("delegation_started", event_types)
        reply_text = "".join(str(evt.get("text") or "") for evt in events if evt.get("type") == "text")
        self.assertEqual(reply_text, "Thomas reply.")
        self.assertNotIn("Got it. Sending", reply_text)
        self.assertEqual(len(_FakeDelegationStarter.calls), 1)
        self.assertEqual(_FakeDelegationStarter.calls[0]["mode"], "max")
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertFalse(bool(_FakeBrain.calls[0].get("dispatch_actionable", True)))

    async def test_session_delegations_endpoint_returns_runtime_state(self):
        with patch(
            "thomas.server.routes.chat_v2.session_active_delegations",
            return_value=[
                {
                    "execution_id": "exec-xyz",
                    "task_id": "task-xyz",
                    "session_id": "sess-delegations",
                    "backend_type": "task_manager",
                    "state": "queued",
                    "summary": "Implement this plan",
                    "last_progress": "Queued for background execution.",
                    "bot_id": "nova",
                }
            ],
        ):
            resp = await self.client.get("/api/v2/chat/session/sess-delegations/delegations")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        delegations = payload.get("delegations") or []
        self.assertEqual(str(payload.get("session_id") or ""), "sess-delegations")
        self.assertTrue(any(str(row.get("task_id") or "") == "task-xyz" for row in delegations))

    async def test_auto_mode_launches_background_delegation_for_actionable_requests(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto",
                    "profile": "local",
                    "mode": "auto",
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertIn("delegation_started", event_types)
        self.assertEqual(len(_FakeDelegationStarter.calls), 1)
        self.assertEqual(_FakeDelegationStarter.calls[0]["mode"], "auto")
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertFalse(bool(_FakeBrain.calls[0].get("dispatch_actionable", True)))
        self.assertTrue(bool(_FakeBrain.calls[0].get("background_ack_only", False)))
        self.assertIn("[Visible reply constraint]", str(_FakeBrain.calls[0].get("prompt") or ""))

    async def test_auto_mode_low_autonomy_keeps_actionable_request_inline(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-inline",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 2,
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertFalse(bool(_FakeBrain.calls[0].get("dispatch_actionable", True)))
        self.assertFalse(bool(_FakeBrain.calls[0].get("background_ack_only", False)))
        self.assertEqual(str(_FakeBrain.calls[0].get("prompt") or ""), "please implement this plan")

    async def test_auto_mode_enables_inline_actionable_for_explicit_file_tool_requests(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-tools",
                    "profile": "local",
                    "mode": "auto",
                    "message": "Use your file tools and name three top-level files in the current repo.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertTrue(bool(_FakeBrain.calls[0].get("dispatch_actionable", False)))

    async def test_auto_mode_can_launch_background_delegation_when_user_requests_reply_first(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-bg",
                    "profile": "local",
                    "mode": "auto",
                    "message": "answer now and delegate the rest in the background",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertIn("delegation_started", event_types)
        self.assertEqual(len(_FakeDelegationStarter.calls), 1)
        self.assertEqual(_FakeDelegationStarter.calls[0]["mode"], "auto")
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertFalse(bool(_FakeBrain.calls[0].get("dispatch_actionable", True)))

    async def test_auto_mode_l4_launches_background_delegation_for_explicit_subagent_request(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-explicit-delegation",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 4,
                    "message": "Spawn exactly three real sub-agents now and keep the response short.",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertIn("delegation_started", event_types)
        self.assertEqual(len(_FakeDelegationStarter.calls), 1)
        self.assertEqual(_FakeDelegationStarter.calls[0]["mode"], "auto")
        self.assertEqual(
            str(_FakeDelegationStarter.calls[0]["prompt"] or ""),
            "Spawn exactly three real sub-agents now and keep the response short.",
        )
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertEqual(
            str(_FakeBrain.calls[0].get("prompt") or ""),
            "Spawn exactly three real sub-agents now and keep the response short.",
        )

    async def test_auto_mode_chat_level_does_not_launch_explicit_subagents(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-no-delegation",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 1,
                    "message": "Spawn exactly three real sub-agents now and keep the response short.",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)

    async def test_chat_v2_forwards_token_economy_to_brain(self):
        _FakeBrain.calls = []
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-economy",
                    "profile": "local",
                    "mode": "auto",
                    "token_economy": "max",
                    "message": "Say only hello.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertEqual(str(_FakeBrain.calls[0].get("token_economy") or ""), "max")

    async def test_chat_v2_transcribe_route_accepts_audio_upload(self):
        from unittest.mock import AsyncMock

        _FakeVoiceBridge.calls = []
        with patch(
            "thomas.server.routes.chat_v2._voice_bridge_for_request", AsyncMock(return_value=_FakeVoiceBridge())
        ):
            form = __import__("aiohttp").FormData()
            form.add_field("audio", b"RIFFfake", filename="sample.wav", content_type="audio/wav")
            resp = await self.client.post(
                "/api/v2/chat/transcribe",
                data=form,
            )

        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(str(payload.get("text") or ""), "hello from mic")
        self.assertEqual(len(_FakeVoiceBridge.calls), 1)
        self.assertEqual(str(_FakeVoiceBridge.calls[0].get("format") or ""), "wav")

    async def test_chat_v2_applies_reasoning_effort_from_payload(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        _FakeLLMClient.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-reasoning-low",
                    "profile": "local",
                    "mode": "auto",
                    "reasoning_effort": "low",
                    "message": "Say only hello.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertTrue(_FakeLLMClient.calls)
        self.assertEqual(_FakeLLMClient.calls[-1]["reasoning_effort"], "low")

    async def test_chat_v2_reuses_cached_llm_for_same_session(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            first = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-cache",
                    "profile": "local",
                    "mode": "auto",
                    "message": "Say only hello.",
                },
            )
            second = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-cache",
                    "profile": "local",
                    "mode": "auto",
                    "message": "Say only hello again.",
                },
            )

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(len(_FakeLLMClient.calls), 1)
        self.assertEqual(_FakeLLMClient.closed, [])

    async def test_chat_v2_refreshes_cached_llm_config(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            first = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-cache-refresh",
                    "profile": "local",
                    "mode": "auto",
                    "reasoning_effort": "low",
                    "message": "Say only hello.",
                },
            )
            second = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-cache-refresh",
                    "profile": "local",
                    "mode": "auto",
                    "reasoning_effort": "high",
                    "message": "Say only hello again.",
                },
            )

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(len(_FakeLLMClient.calls), 1)
        cache = self.app[chat_v2_routes.APP_SESSION_LLM_CACHE]
        entry = cache["sess-cache-refresh"]
        self.assertEqual(getattr(entry.llm.config, "reasoning_effort", ""), "high")

    async def test_get_or_create_session_llm_uses_warm_codex_provider(self):
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        warm_provider = object()
        model_cfg = ModelConfig(name="codex", provider="codex", model="gpt-5.4")
        pool_key = chat_v2_routes._warm_codex_pool_key(model_cfg)
        self.app[chat_v2_routes.APP_SESSION_LLM_CACHE].clear()
        self.app[chat_v2_routes.APP_WARM_CODEX_POOL].clear()
        self.app[chat_v2_routes.APP_WARM_CODEX_TASKS].clear()
        self.app[chat_v2_routes.APP_WARM_CODEX_POOL][pool_key] = warm_provider

        with (
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2._schedule_codex_prewarm", lambda app, cfg: None),
        ):
            llm, _lock = await chat_v2_routes._get_or_create_session_llm(
                self.app,
                session_id="sess-warm-provider",
                model_cfg=model_cfg,
                fallback_cfgs=[],
                failover_enabled=False,
            )

        self.assertEqual(len(_FakeLLMClient.calls), 1)
        self.assertIs(getattr(llm, "_codex_provider", None), warm_provider)
        self.assertNotIn(pool_key, self.app[chat_v2_routes.APP_WARM_CODEX_POOL])

    async def test_chat_v2_session_delete_evicts_cached_llm(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            create = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-cache-delete",
                    "profile": "local",
                    "mode": "auto",
                    "message": "Say only hello.",
                },
            )
            delete = await self.client.delete("/api/v2/chat/session/sess-cache-delete")

        self.assertEqual(create.status, 200)
        self.assertEqual(delete.status, 200)
        self.assertEqual(len(_FakeLLMClient.calls), 1)
        self.assertEqual(len(_FakeLLMClient.closed), 1)
        cache = self.app[chat_v2_routes.APP_SESSION_LLM_CACHE]
        self.assertNotIn("sess-cache-delete", cache)

    async def test_reply_first_background_constrains_visible_prompt(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        prompt = (
            "Reply fast with one sentence now about the best way to organize a busy Friday. "
            "In the background, draft a detailed hour-by-hour Friday plan."
        )
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-bg-prompt",
                    "profile": "local",
                    "mode": "auto",
                    "message": prompt,
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(len(_FakeBrain.calls), 1)
        visible_prompt = str(_FakeBrain.calls[0].get("prompt") or "")
        self.assertIn("[Visible reply constraint]", visible_prompt)
        self.assertIn("Reply fast with one sentence now", visible_prompt)
        self.assertNotIn("draft a detailed hour-by-hour Friday plan.", visible_prompt)

    async def test_chat_v2_rejects_empty_message_payload(self):
        resp = await self.client.post(
            "/api/v2/chat",
            json={
                "session_id": "sess-empty",
                "profile": "local",
                "mode": "auto",
            },
        )

        self.assertEqual(resp.status, 400)
        self.assertEqual((await resp.json())["error"], "Empty message")

    async def test_chat_v2_text_fallback_attaches_docs_and_images(self):
        _FakeBrain.calls = []
        long_text = "A" * 50010
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-docs-images",
                    "profile": "local",
                    "mode": "auto",
                    "text": "Summarize these files.",
                    "docs": [
                        {"name": "notes.txt", "text": long_text},
                        {"name": "empty.txt", "text": "   "},
                        "ignore-me",
                    ],
                    "images": [
                        {"data_url": "data:image/png;base64,aaa"},
                        {"data_url": "data:image/png;base64,bbb"},
                        {"data_url": "data:image/png;base64,ccc"},
                        {"data_url": "data:image/png;base64,ddd"},
                        {"data_url": "data:image/png;base64,eee"},
                    ],
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(len(_FakeBrain.calls), 1)
        prompt = str(_FakeBrain.calls[0].get("prompt") or "")
        images = _FakeBrain.calls[0].get("images") or []
        self.assertIn("[Attached documents]", prompt)
        self.assertIn("--- notes.txt ---", prompt)
        self.assertIn("... (truncated)", prompt)
        self.assertEqual(len(images), 4)

    async def test_chat_v2_without_app_config_uses_no_llm_lock_path(self):
        _FakeBrain.calls = []
        self.app[chat_v2_routes.APP_CONFIG] = None
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-no-config",
                    "mode": "auto",
                    "message": "Say hello without config.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(len(_FakeBrain.calls), 1)

    async def test_chat_v2_surfaces_launcher_failure_as_delegation_failed_event(self):
        _FakeBrain.calls = []

        async def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
            _ = args, kwargs
            raise RuntimeError("delegation launcher blew up")

        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _boom),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-launcher-fail",
                    "profile": "local",
                    "mode": "max",
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        failure_events = [evt for evt in events if evt.get("type") == "delegation_failed"]
        self.assertEqual(len(failure_events), 1)
        self.assertIn("delegation launcher blew up", str(failure_events[0].get("last_progress") or ""))

    async def test_chat_v2_emits_error_event_when_brain_raises(self):
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrainBoom):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-brain-fail",
                    "profile": "local",
                    "mode": "auto",
                    "message": "Say hello.",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        error_events = [evt for evt in events if evt.get("type") == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertIn("brain exploded", str(error_events[0].get("error") or ""))

    async def test_chat_v2_transcribe_requires_audio_and_surfaces_errors(self):
        wrong_type = await self.client.post("/api/v2/chat/transcribe", data=b"raw-bytes")
        self.assertEqual(wrong_type.status, 400)

        from unittest.mock import AsyncMock

        with patch(
            "thomas.server.routes.chat_v2._voice_bridge_for_request", AsyncMock(return_value=_FakeVoiceBridge())
        ):
            missing_audio_form = __import__("aiohttp").FormData()
            missing_audio_form.add_field("note", b"no audio here", filename="note.txt", content_type="text/plain")
            missing = await self.client.post("/api/v2/chat/transcribe", data=missing_audio_form)
        self.assertEqual(missing.status, 400)
        self.assertEqual((await missing.json())["error"], "Missing audio upload")

        with patch(
            "thomas.server.routes.chat_v2._voice_bridge_for_request", AsyncMock(return_value=_VoiceProviderBoom())
        ):
            form = __import__("aiohttp").FormData()
            form.add_field("audio", b"RIFFfake", filename="sample.wav", content_type="audio/wav")
            provider_fail = await self.client.post("/api/v2/chat/transcribe", data=form)
        self.assertEqual(provider_fail.status, 503)

        with patch(
            "thomas.server.routes.chat_v2._voice_bridge_for_request", AsyncMock(return_value=_VoiceGenericBoom())
        ):
            form = __import__("aiohttp").FormData()
            form.add_field("audio", b"RIFFfake", filename="sample.wav", content_type="audio/wav")
            generic_fail = await self.client.post("/api/v2/chat/transcribe", data=form)
        self.assertEqual(generic_fail.status, 500)
        self.assertIn("Transcription failed", (await generic_fail.json())["error"])

        with (
            patch("thomas.server.routes.chat_v2._MAX_TRANSCRIBE_BYTES", 4),
            patch("thomas.server.routes.chat_v2._voice_bridge_for_request", AsyncMock(return_value=_FakeVoiceBridge())),
        ):
            form = __import__("aiohttp").FormData()
            form.add_field("audio", b"012345", filename="sample.wav", content_type="audio/wav")
            too_large = await self.client.post("/api/v2/chat/transcribe", data=form)
        self.assertEqual(too_large.status, 413)
        self.assertEqual((await too_large.json())["error"], "Audio upload too large")

    async def test_session_get_and_specialists_list_routes(self):
        missing = await self.client.get("/api/v2/chat/session/missing-session")
        self.assertEqual(missing.status, 404)

        _FakeBrain.calls = []
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain):
            created = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-route-check",
                    "profile": "local",
                    "mode": "auto",
                    "message": "Say hello.",
                },
            )
        self.assertEqual(created.status, 200)

        existing = await self.client.get("/api/v2/chat/session/sess-route-check")
        self.assertEqual(existing.status, 200)
        payload = await existing.json()
        self.assertEqual(payload["session_id"], "sess-route-check")
        self.assertIn("messages", payload["conversation"])

        fake_specialist = SimpleNamespace(
            specialist_id="reasoning",
            description="Reasoning specialist",
            capabilities={"reason", "chat"},
            check_health=lambda: None,
        )

        async def _fake_health():
            return SimpleNamespace(healthy=True, message="OK")

        fake_specialist.check_health = _fake_health
        self.app[chat_v2_routes.APP_SPECIALIST_REGISTRY] = SimpleNamespace(all_specialists=[fake_specialist])
        specialists = await self.client.get("/api/v2/chat/specialists")
        self.assertEqual(specialists.status, 200)
        specialists_payload = await specialists.json()
        self.assertEqual(specialists_payload["specialists"][0]["id"], "reasoning")


if __name__ == "__main__":
    unittest.main()
