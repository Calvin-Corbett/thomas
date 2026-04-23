import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import AioHTTPTestCase

from tests.test_server_chat_v2_support import (
    FakeBrain as _FakeBrain,
)
from tests.test_server_chat_v2_support import (
    FakeBrainBoom as _FakeBrainBoom,
)
from tests.test_server_chat_v2_support import (
    FakeDispatch as _FakeDispatch,
)
from tests.test_server_chat_v2_support import (
    FakeLLMClient as _FakeLLMClient,
)
from tests.test_server_chat_v2_support import (
    FakeVoiceBridge as _FakeVoiceBridge,
)
from tests.test_server_chat_v2_support import (
    VoiceGenericBoom as _VoiceGenericBoom,
)
from tests.test_server_chat_v2_support import (
    VoiceProviderBoom as _VoiceProviderBoom,
)
from tests.test_server_chat_v2_support import (
    fake_stream_ack as _fake_stream_ack,
)
from tests.test_server_chat_v2_support import (
    parse_ndjson as _parse_ndjson,
)
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.routes import chat_v2 as chat_v2_routes


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

    async def test_max_mode_actionable_request_uses_task_manager_reply_path(self):
        _FakeBrain.calls = []
        _FakeDispatch.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.is_task_manager_dispatch_ready", return_value=True),
            patch("thomas.server.routes.chat_v2.stream_task_start_acknowledgment", _fake_stream_ack),
            patch("thomas.server.routes.chat_v2.dispatch_async", _FakeDispatch.run),
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
        self.assertIn("task_dispatched", event_types)
        reply_text = "".join(str(evt.get("text") or "") for evt in events if evt.get("type") == "text")
        self.assertIn("Yeah, I'm getting started now.", reply_text)
        self.assertEqual(len(_FakeDispatch.calls), 1)
        self.assertEqual(str(_FakeDispatch.calls[0]["session_id"]), "sess-max")
        self.assertEqual(len(_FakeBrain.calls), 0)

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

    async def test_auto_mode_actionable_request_uses_task_manager_reply_path(self):
        _FakeBrain.calls = []
        _FakeDispatch.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.is_task_manager_dispatch_ready", return_value=True),
            patch("thomas.server.routes.chat_v2.stream_task_start_acknowledgment", _fake_stream_ack),
            patch("thomas.server.routes.chat_v2.dispatch_async", _FakeDispatch.run),
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
        self.assertIn("task_dispatched", event_types)
        self.assertEqual(len(_FakeDispatch.calls), 1)
        self.assertEqual(len(_FakeBrain.calls), 0)

    async def test_low_autonomy_cannot_bypass_actionable_dispatch(self):
        _FakeBrain.calls = []
        _FakeDispatch.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.is_task_manager_dispatch_ready", return_value=True),
            patch("thomas.server.routes.chat_v2.stream_task_start_acknowledgment", _fake_stream_ack),
            patch("thomas.server.routes.chat_v2.dispatch_async", _FakeDispatch.run),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-inline",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 1,
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertIn("task_dispatched", event_types)
        self.assertEqual(len(_FakeDispatch.calls), 1)
        self.assertEqual(len(_FakeBrain.calls), 0)

    async def test_explicit_file_tool_request_prefers_task_manager_when_dispatch_is_ready(self):
        _FakeBrain.calls = []
        _FakeDispatch.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.is_task_manager_dispatch_ready", return_value=True),
            patch("thomas.server.routes.chat_v2.stream_task_start_acknowledgment", _fake_stream_ack),
            patch("thomas.server.routes.chat_v2.dispatch_async", _FakeDispatch.run),
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
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertIn("task_dispatched", event_types)
        self.assertEqual(len(_FakeDispatch.calls), 1)
        self.assertEqual(len(_FakeBrain.calls), 0)

    async def test_deterministic_fast_tools_prompt_prefers_task_manager_when_dispatch_is_ready(self):
        _FakeBrain.calls = []
        _FakeDispatch.calls = []

        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.should_dispatch", return_value=SimpleNamespace(action="dispatch")),
            patch("thomas.server.routes.chat_v2.is_task_manager_dispatch_ready", return_value=True),
            patch("thomas.server.routes.chat_v2.stream_task_start_acknowledgment", _fake_stream_ack),
            patch("thomas.server.routes.chat_v2.dispatch_async", _FakeDispatch.run),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-inline-fast-tools",
                    "profile": "local",
                    "mode": "max",
                    "message": (
                        "Use your tools to create the file "
                        "D:\\Desktop\\thomas-inline-fast.txt containing exactly OK, "
                        "then answer with only the full file path on one line and the file contents on the next line."
                    ),
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertIn("task_dispatched", event_types)
        self.assertEqual(len(_FakeDispatch.calls), 1)
        self.assertEqual(len(_FakeBrain.calls), 0)

    async def test_direct_web_headline_prompt_prefers_task_manager_when_dispatch_is_ready(self):
        _FakeBrain.calls = []
        _FakeDispatch.calls = []

        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.should_dispatch", return_value=SimpleNamespace(action="dispatch")),
            patch("thomas.server.routes.chat_v2.is_task_manager_dispatch_ready", return_value=True),
            patch("thomas.server.routes.chat_v2.stream_task_start_acknowledgment", _fake_stream_ack),
            patch("thomas.server.routes.chat_v2.dispatch_async", _FakeDispatch.run),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-inline-fast-web",
                    "profile": "local",
                    "mode": "max",
                    "message": "Open https://open-claw.org and answer with only the exact main headline text.",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertIn("task_dispatched", event_types)
        self.assertEqual(len(_FakeDispatch.calls), 1)
        self.assertEqual(len(_FakeBrain.calls), 0)

    async def test_reply_first_prompt_still_uses_task_manager_path(self):
        _FakeBrain.calls = []
        _FakeDispatch.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.is_task_manager_dispatch_ready", return_value=True),
            patch("thomas.server.routes.chat_v2.stream_task_start_acknowledgment", _fake_stream_ack),
            patch("thomas.server.routes.chat_v2.dispatch_async", _FakeDispatch.run),
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
        self.assertIn("task_dispatched", [str(evt.get("type") or "") for evt in events])
        self.assertEqual(len(_FakeDispatch.calls), 1)
        self.assertEqual(len(_FakeBrain.calls), 0)

    async def test_explicit_subagent_prompt_uses_task_manager_path(self):
        _FakeBrain.calls = []
        _FakeDispatch.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.is_task_manager_dispatch_ready", return_value=True),
            patch("thomas.server.routes.chat_v2.stream_task_start_acknowledgment", _fake_stream_ack),
            patch("thomas.server.routes.chat_v2.dispatch_async", _FakeDispatch.run),
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
        self.assertIn("task_dispatched", [str(evt.get("type") or "") for evt in events])
        self.assertEqual(len(_FakeDispatch.calls), 1)
        self.assertEqual(len(_FakeBrain.calls), 0)

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
        _FakeLLMClient.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
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
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
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
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
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
        _FakeLLMClient.calls = []
        _FakeLLMClient.closed = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
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

    async def test_inline_conversation_prompt_is_passed_through_unchanged(self):
        _FakeBrain.calls = []
        prompt = "What is the best way to organize a busy Friday?"
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
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
        self.assertEqual(str(_FakeBrain.calls[0].get("prompt") or ""), prompt)

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

    async def test_chat_v2_surfaces_dispatch_failure_as_error_event(self):
        async def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
            _ = args, kwargs
            raise RuntimeError("dispatch exploded")

        with (
            patch("thomas.server.routes.chat_v2.stream_task_start_acknowledgment", _fake_stream_ack),
            patch("thomas.server.routes.chat_v2.is_task_manager_dispatch_ready", return_value=True),
            patch("thomas.server.routes.chat_v2.dispatch_async", _boom),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-dispatch-fail",
                    "profile": "local",
                    "mode": "auto",
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        error_events = [evt for evt in events if evt.get("type") == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertIn("dispatch exploded", str(error_events[0].get("error") or ""))

    async def test_actionable_request_falls_back_to_inline_brain_when_task_manager_is_cold(self):
        _FakeBrain.calls = []
        _FakeDispatch.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.is_task_manager_dispatch_ready", return_value=False),
            patch("thomas.server.routes.chat_v2.dispatch_async", _FakeDispatch.run),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-inline-fallback",
                    "profile": "local",
                    "mode": "auto",
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertIn("Thomas reply.", "".join(str(evt.get("text") or "") for evt in events))
        self.assertEqual(len(_FakeDispatch.calls), 0)
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertTrue(_FakeBrain.calls[0]["dispatch_actionable"])

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
