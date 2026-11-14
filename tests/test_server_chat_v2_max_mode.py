"""Chat v2 routes: the stream, the prompt the model sees, the legacy alias, voice,
errors and session reads.

Dispatch tests live in tests/test_server_chat_v2_max_mode_dispatch.py and
per-turn controls in tests/test_server_chat_v2_max_mode_controls.py; the fakes
and the app fixture are in tests/_chat_v2_max_mode_support.py.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests import _chat_v2_max_mode_support as support
from tests._chat_v2_max_mode_support import (
    _FakeBrain,
    _FakeBrainBoom,
    _FakeDelegationStarter,
    _FakeVoiceBridge,
    _parse_ndjson,
    _VoiceGenericBoom,
    _VoiceProviderBoom,
)
from thomas.server.routes import chat_v2 as chat_v2_routes


class TestServerChatV2MaxMode(support.ChatV2MaxModeCase):
    async def test_max_mode_streams_reply_and_leaves_dispatch_to_model(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
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
        with patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain):
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
            with patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain):
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

    async def test_reply_first_words_are_not_rewritten_before_model(self):
        _FakeBrain.calls = []
        _FakeDelegationStarter.calls = []
        prompt = (
            "Reply fast with one sentence now about the best way to organize a busy Friday. "
            "In the background, draft a detailed hour-by-hour Friday plan."
        )
        with (
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
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
        with patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain):
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
        with patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain):
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
            patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain),
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
        with patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrainBoom):
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
        with patch("thomas.server.routes.chat_v2_support.OrchestratorBrain", _FakeBrain):
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
