import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.routes import chat_v2 as chat_v2_routes
from thomas.tools.voice import AudioData, VoiceProviderException


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
    init_calls = []

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _FakeBrain.init_calls.append(dict(kwargs or {}))

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

    def __init__(
        self,
        config,
        fallback_configs=None,
        failover_enabled=False,
        failover_cooldown_s=300,
        failover_on_auth_error=False,
        max_retries=3,
        base_retry_delay_s=0.8,
        request_overrides=None,
    ):  # noqa: ANN001
        self.config = config
        self._primary_config = config
        self._fallback_configs = list(fallback_configs or [])
        self._failover_enabled = bool(failover_enabled)
        self._failover_cooldown_s = int(failover_cooldown_s)
        self._failover_on_auth_error = bool(failover_on_auth_error)
        self._max_retries = int(max_retries)
        self._base_retry_delay = float(base_retry_delay_s)
        self._request_overrides = dict(request_overrides or {})
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

    def runtime_trace(self):  # noqa: ANN201
        runtime = {
            "profile": getattr(self.config, "name", ""),
            "provider": getattr(self.config, "provider", ""),
            "model": getattr(self.config, "model", ""),
            "base_url": getattr(self.config, "base_url", ""),
        }
        return {
            "requested": dict(runtime),
            "active": dict(runtime),
            "failover_enabled": self._failover_enabled,
            "failover_used": False,
            "attempts": [{**runtime, "status": "success"}],
        }


class _FakeDelegationStarter:
    calls = []

    @staticmethod
    async def start(
        app,
        *,
        session_id,
        prompt,
        mode,
        recent_messages,
        emit_event,
        repo_root=None,
        force=False,
        autonomy_level=4,
        profile=None,
        model_id=None,
        reasoning_effort=None,
        effort="diligent",
        file_access=None,
        guardrails="",
        guardrail_modes=None,
        session_llm=None,
        work_context_id="",
        memory_enabled=True,
        runtime_policy=None,
    ):  # noqa: ANN001
        _ = app
        _ = repo_root
        _ = guardrail_modes
        _ = session_llm
        _FakeDelegationStarter.calls.append(
            {
                "session_id": session_id,
                "prompt": prompt,
                "mode": mode,
                "recent_messages": list(recent_messages or []),
                "profile": profile,
                "model_id": model_id,
                "reasoning_effort": reasoning_effort,
                "effort": effort,
                "file_access": file_access,
                "guardrails": guardrails,
                "force": force,
                "autonomy_level": autonomy_level,
                "work_context_id": work_context_id,
                "memory_enabled": memory_enabled,
                "runtime_policy": dict(runtime_policy or {}),
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

    def __init__(self) -> None:
        self._current_stt = SimpleNamespace(get_provider_name=lambda: "fake_stt")
        self._current_tts = SimpleNamespace(get_provider_name=lambda: "fake_tts")

    async def transcribe(self, audio):  # noqa: ANN001
        _FakeVoiceBridge.calls.append(
            {
                "format": getattr(audio, "format", ""),
                "bytes": len(getattr(audio, "data", b"")),
                "language": getattr(audio, "language", ""),
            }
        )
        return "hello from mic"

    async def synthesize(self, text, voice="default", speed=1.0):  # noqa: ANN001, ANN201
        _FakeVoiceBridge.calls.append({"text": text, "voice": voice, "speed": speed})
        return AudioData(data=b"RIFFfakeWAVE", format="wav", sample_rate=16000, duration_ms=250, language="en-US")


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
        self._environment = patch.dict(
            "os.environ",
            {"THOMAS_DB_PATH": f"{self._tmpdir.name}/preferences.db"},
        )
        self._environment.start()

    def tearDown(self) -> None:
        try:
            self._environment.stop()
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

    async def test_max_mode_streams_reply_and_leaves_dispatch_to_model(self):
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
                    "model_id": "gpt-5.6-luna",
                    "reasoning_effort": "xhigh",
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        self.assertIn("application/x-ndjson", str(resp.headers.get("Content-Type") or ""))

        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertNotIn("delegation_started", event_types)
        reply_text = "".join(str(evt.get("text") or "") for evt in events if evt.get("type") == "text")
        self.assertEqual(reply_text, "Thomas reply.")
        self.assertNotIn("Got it. Sending", reply_text)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)

    async def test_session_delegations_endpoint_returns_runtime_state(self):
        with patch(
            "thomas.server.routes.chat_v2_request_support.session_active_delegations",
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
        receipt = delegations[0].get("receipt") or {}
        self.assertEqual(receipt.get("kind"), "delegated")
        self.assertEqual(receipt.get("session_id"), "sess-delegations")
        self.assertEqual(receipt.get("execution_id"), "exec-xyz")
        self.assertIsNone(receipt.get("ok"))

    async def test_legacy_chat_url_is_a_deprecated_alias_for_v2(self):
        _FakeBrain.calls = []
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": "sess-v1-alias",
                    "profile": "local",
                    "text": "Use the canonical engine.",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertEqual(resp.headers.get("X-Thomas-Chat-Engine"), "v2")
        self.assertEqual(resp.headers.get("Deprecation"), "true")
        self.assertIn("successor-version", str(resp.headers.get("Link") or ""))
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertTrue(any(event.get("type") == "done" for event in events))

    async def test_legacy_agent_modes_migrate_to_v2_max(self):
        for legacy_mode in ("batch", "swarm"):
            _FakeBrain.calls = []
            with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain):
                resp = await self.client.post(
                    "/api/chat",
                    json={
                        "session_id": f"sess-{legacy_mode}-migration",
                        "profile": "local",
                        "mode": legacy_mode,
                        "text": "Run this long-horizon request.",
                    },
                )

            self.assertEqual(resp.status, 200)
            events = _parse_ndjson(await resp.text())
            migrated = [event for event in events if event.get("type") == "mode_migrated"]
            self.assertEqual(len(migrated), 1)
            self.assertEqual(migrated[0].get("from"), legacy_mode)
            self.assertEqual(migrated[0].get("to"), "max")
            self.assertEqual(_FakeBrain.calls[0].get("mode"), "max")

    async def test_auto_mode_wires_send_task_at_agent_autonomy_no_regex_launch(self):
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
                    # At L3+ the MODEL gets the send_task tool and decides whether to
                    # hand work off — organically, no regex pre-classification, no
                    # auto-launch behind its back.
                    "autonomy_level": 3,
                    "message": "please implement this plan",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        # No regex-driven auto-launch: dispatch is the model's call via send_task.
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(len(_FakeDelegationStarter.calls), 0)
        self.assertEqual(len(_FakeBrain.calls), 1)
        # The send_task callback IS wired at L3 (the model can dispatch organically).
        self.assertIsNotNone(_FakeBrain.calls[0].get("send_task"))
        # Thomas also receives the bounded governed-operator callback, never the
        # raw registry. The controller itself enforces autonomy and guardrails.
        self.assertIsNotNone(_FakeBrain.calls[0].get("operate"))
        # No canned background-ack path; the prompt is unmodified (no visible-reply hack).
        self.assertFalse(bool(_FakeBrain.calls[0].get("background_ack_only", False)))
        self.assertEqual(str(_FakeBrain.calls[0].get("prompt") or ""), "please implement this plan")

    async def test_live_repo_words_do_not_force_background_dispatch(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        prompt = (
            "Development task. Work in the live Thomas repo. Locally uninstall these "
            "marketplace modules: Life Manager, Brownies, Smart Home, and Telegram Channel. "
            "Use your file tools for repo edits."
        )
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-auto-live-repo",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 3,
                    "file_access": "project",
                    "message": prompt,
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        event_types = [str(evt.get("type") or "") for evt in events]
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertIsNotNone(_FakeBrain.calls[0].get("send_task"))
        self.assertEqual(_FakeBrain.calls[0].get("prompt"), prompt)

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
        self.assertNotIn("dispatch_actionable", _FakeBrain.calls[0])
        self.assertNotIn("background_ack_only", _FakeBrain.calls[0])
        self.assertEqual(str(_FakeBrain.calls[0].get("prompt") or ""), "please implement this plan")

    async def test_file_tool_words_do_not_toggle_a_hidden_actionable_route(self):
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
        self.assertNotIn("dispatch_actionable", _FakeBrain.calls[0])

    async def test_reply_first_words_do_not_prelaunch_background_work(self):
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
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)

    async def test_subagent_words_do_not_prelaunch_background_work(self):
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
        self.assertNotIn("delegation_started", event_types)
        self.assertEqual(_FakeDelegationStarter.calls, [])
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

    async def test_token_economy_does_not_prelaunch_delegation(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-economy",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 4,
                    "token_economy": "max",
                    "message": "Say only hello.",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertNotIn("delegation_started", [str(event.get("type") or "") for event in events])
        reply_text = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text")
        self.assertEqual(reply_text, "Thomas reply.")
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertIsNotNone(_FakeBrain.calls[0].get("send_task"))
        self.assertEqual(_FakeDelegationStarter.calls, [])

    async def test_chat_v2_max_token_economy_respects_low_autonomy_cap(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-economy-low-autonomy",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 2,
                    "token_economy": "max",
                    "message": "Compare the three options.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(len(_FakeBrain.calls), 1)
        self.assertEqual(_FakeDelegationStarter.calls, [])

    async def test_max_mode_controls_do_not_start_worker_without_model_call(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-worker-controls",
                    "profile": "local",
                    "mode": "max",
                    "file_access": "full",
                    "token_economy": "max",
                    "thomas_guardrails": "fortress",
                    "message": "Create a safe workspace artifact.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(len(_FakeBrain.calls), 1)

    async def test_chat_v2_transcribe_route_accepts_audio_upload(self):
        from unittest.mock import AsyncMock

        _FakeVoiceBridge.calls = []
        with patch(
            "thomas.server.routes.chat_v2._voice_bridge_for_request", AsyncMock(return_value=_FakeVoiceBridge())
        ):
            form = __import__("aiohttp").FormData()
            form.add_field("audio", b"RIFFfake", filename="sample.wav", content_type="audio/wav")
            form.add_field("language", "en-US")
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
        self.assertEqual(str(_FakeVoiceBridge.calls[0].get("language") or ""), "en-US")

    async def test_chat_v2_speak_route_returns_audio_and_provider_receipt(self):
        from unittest.mock import AsyncMock

        _FakeVoiceBridge.calls = []
        with patch(
            "thomas.server.routes.chat_v2._voice_bridge_for_request",
            AsyncMock(return_value=_FakeVoiceBridge()),
        ):
            response = await self.client.post(
                "/api/v2/chat/speak",
                json={"text": "hello owner", "voice": "default", "speed": 1.25},
            )

        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), b"RIFFfakeWAVE")
        self.assertEqual(response.headers["Content-Type"], "audio/wav")
        self.assertEqual(response.headers["X-Thomas-Voice-Provider"], "fake_tts")
        self.assertEqual(response.headers["X-Thomas-Audio-Language"], "en-US")
        self.assertEqual(_FakeVoiceBridge.calls[-1]["speed"], 1.25)

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

    async def test_chat_v2_memory_toggle_disables_long_term_memory_for_turn(self):
        _FakeBrain.calls = []
        _FakeBrain.init_calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-memory-disabled",
                    "profile": "local",
                    "mode": "auto",
                    "memory": False,
                    "message": "Say only hello.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertTrue(_FakeBrain.init_calls)
        self.assertIsNone(_FakeBrain.init_calls[-1]["memory_engine"])

    async def test_chat_v2_persists_memory_off_across_later_model_turns(self):
        _FakeBrain.init_calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            first = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-memory-persisted-off",
                    "profile": "local",
                    "mode": "max",
                    "memory": False,
                    "message": "Build a small report.",
                },
            )
            second = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-memory-persisted-off",
                    "mode": "max",
                    "message": "Build another small report.",
                },
            )

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertIsNone(_FakeBrain.init_calls[-1]["memory_engine"])
        meta = await self.app[chat_v2_routes.APP_SESSION_STORE].load_meta("sess-memory-persisted-off")
        self.assertIsNotNone(meta)
        self.assertFalse(meta.memory_enabled)

    async def test_reasoning_effort_does_not_override_independent_token_economy(self):
        _FakeBrain.calls = []
        _FakeLLMClient.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.LLMClient", _FakeLLMClient),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _FakeDelegationStarter.start),
        ):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-independent-settings",
                    "profile": "local",
                    "mode": "max",
                    "reasoning_effort": "xhigh",
                    "token_economy": "cheap",
                    "message": "Build a small report.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertEqual(_FakeDelegationStarter.calls, [])
        self.assertEqual(_FakeLLMClient.calls[-1]["reasoning_effort"], "xhigh")
        self.assertEqual(_FakeBrain.calls[-1]["token_economy"], "cheap")

    async def test_chat_v2_applies_model_id_from_payload(self):
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
                    "session_id": "sess-model-override",
                    "profile": "local",
                    "mode": "auto",
                    "model_id": "office-chat-model",
                    "message": "Say only hello.",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertTrue(_FakeLLMClient.calls)
        self.assertEqual(_FakeLLMClient.calls[-1]["model"], "office-chat-model")
        runtime_event = next(event for event in _parse_ndjson(await resp.text()) if event["type"] == "model_runtime")
        self.assertEqual(runtime_event["runtime"]["requested"]["profile"], "local")
        self.assertEqual(runtime_event["runtime"]["active"]["model"], "office-chat-model")
        self.assertFalse(runtime_event["runtime"]["failover_used"])

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

    async def test_chat_v2_reuses_saved_model_and_reasoning_when_later_turn_omits_them(self):
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
                    "session_id": "sess-saved-settings",
                    "profile": "local",
                    "mode": "auto",
                    "autonomy_level": 4,
                    "model_id": "gpt-5.6-terra",
                    "reasoning_effort": "xhigh",
                    "message": "Say only hello.",
                },
            )
            # Simulate a process-local LLM cache miss. The durable SessionMeta,
            # rather than the first client instance, must restore the settings.
            self.app[chat_v2_routes.APP_SESSION_LLM_CACHE].clear()
            second = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-saved-settings",
                    "mode": "max",
                    "message": "Build a small text report in the background.",
                },
            )

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(len(_FakeLLMClient.calls), 2)
        self.assertEqual(_FakeLLMClient.calls[-1]["model"], "gpt-5.6-terra")
        self.assertEqual(_FakeLLMClient.calls[-1]["reasoning_effort"], "xhigh")
        self.assertEqual(_FakeDelegationStarter.calls, [])

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

    async def test_reply_first_words_are_not_rewritten_before_model(self):
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
        self.assertEqual(visible_prompt, prompt)
        self.assertEqual(_FakeDelegationStarter.calls, [])

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

    async def test_launcher_is_not_called_without_structured_model_dispatch(self):
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
        self.assertEqual(failure_events, [])
        self.assertEqual(len(_FakeBrain.calls), 1)

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
        self.assertEqual(error_events[0].get("error"), "Thomas could not complete this chat turn safely.")
        self.assertNotIn("brain exploded", str(error_events[0]))

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
