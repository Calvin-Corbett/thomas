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
        conversation = conversation.append_message("assistant", "MAX_MODE_OK")
        await dispatcher.emit_text("MAX_MODE_OK")
        await dispatcher.emit_done(
            session_id=str(kwargs.get("session_id") or ""),
            conversation_version=conversation.version,
            thinking_summary="canonical_v2",
            iterations=1,
            tool_calls=0,
        )
        return conversation


class _ForbiddenBatchClient:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("retired provider batch client must not be constructed")


async def _no_background_delegation(*_args: Any, **_kwargs: Any) -> None:
    return None


class TestServerBatchMode(AioHTTPTestCase):
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
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_batch_payload_migrates_to_max_without_provider_batch_runtime(self):
        _FakeBrain.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _no_background_delegation),
            patch("thomas.server.app.OpenAICompatBatchClient", _ForbiddenBatchClient),
        ):
            resp = await self.client.post(
                "/api/chat",
                json={"profile": "local", "mode": "batch", "text": "run this as long horizon"},
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        migration = [event for event in events if event.get("type") == "mode_migrated"]
        self.assertEqual(migration[0].get("to"), "max")
        self.assertEqual(_FakeBrain.calls[0].get("mode"), "max")
        self.assertTrue(any(event.get("type") == "done" for event in events))

    async def test_conversational_batch_control_returns_a_max_patch(self):
        resp = await self.client.post(
            "/api/chat",
            json={"profile": "local", "mode": "fast", "text": "set mode to batch"},
        )
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        patch_events = [event for event in events if event.get("type") == "ui_state_patch"]
        self.assertEqual((patch_events[0].get("patch") or {}).get("mode"), "max")
        self.assertIn(
            "batch execution mode is retired",
            "".join(str(event.get("text") or "") for event in events if event.get("type") == "text"),
        )


if __name__ == "__main__":
    unittest.main()
