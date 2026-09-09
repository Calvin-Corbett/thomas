from __future__ import annotations

import json
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


def _parse_ndjson(blob: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in str(blob or "").splitlines() if line.strip()]


class _FakeBrain:
    calls: list[dict[str, Any]] = []

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def process_message(self, *, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        self.calls.append({"prompt": prompt, **kwargs})
        conversation = conversation.append_message("user", prompt)
        conversation = conversation.append_message("assistant", "MODEL_OWNED_OK")
        await dispatcher.emit_text("MODEL_OWNED_OK")
        await dispatcher.emit_done(
            session_id=str(kwargs.get("session_id") or ""),
            conversation_version=conversation.version,
            thinking_summary="canonical_v2",
            iterations=1,
            tool_calls=0,
        )
        return conversation


async def _no_background_delegation(*_args: Any, **_kwargs: Any) -> None:
    return None


class TestServerStructuredChatControls(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def _post_with_fake_brain(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        _FakeBrain.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _no_background_delegation),
        ):
            response = await self.client.post("/api/chat", json=payload)
        self.assertEqual(response.status, 200)
        return _parse_ndjson(await response.text())

    async def test_ordinary_control_wording_reaches_model_without_hidden_ui_action(self):
        prompt = "set mode to batch"
        events = await self._post_with_fake_brain(
            {
                "profile": "local",
                "mode": "fast",
                "text": prompt,
            }
        )

        self.assertEqual(_FakeBrain.calls[0].get("prompt"), prompt)
        self.assertEqual(_FakeBrain.calls[0].get("mode"), "fast")
        self.assertFalse(any(event.get("type") == "ui_state_patch" for event in events))
        self.assertFalse(any(event.get("type") == "operator_action" for event in events))
        self.assertTrue(any(event.get("type") == "text" and event.get("text") == "MODEL_OWNED_OK" for event in events))

    async def test_structured_mode_and_autonomy_fields_control_runtime(self):
        events = await self._post_with_fake_brain(
            {
                "profile": "local",
                "mode": "batch",
                "autonomy_level": 4,
                "text": "run the supplied task",
            }
        )

        self.assertEqual(_FakeBrain.calls[0].get("prompt"), "run the supplied task")
        self.assertEqual(_FakeBrain.calls[0].get("mode"), "max")
        self.assertEqual(_FakeBrain.calls[0].get("autonomy_level"), 4)
        migration = [event for event in events if event.get("type") == "mode_migrated"]
        self.assertEqual(migration[0].get("from"), "batch")
        self.assertEqual(migration[0].get("to"), "max")

    async def test_unknown_explicit_model_alias_is_rejected(self):
        session_response = await self.client.post("/api/session/new")
        self.assertEqual(session_response.status, 200)
        session_id = str((await session_response.json()).get("session_id") or "")
        self.assertTrue(session_id)

        response = await self.client.post(
            "/api/chat",
            json={
                "sessionId": session_id,
                "model": "not-a-real-profile",
                "mode": "fast",
                "message": "hello",
            },
        )

        self.assertEqual(response.status, 400)
        self.assertIn("unknown profile", await response.text())


if __name__ == "__main__":
    unittest.main()
