import json
import os
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
        conversation = conversation.append_message("assistant", "CONVO_OK")
        await dispatcher.emit_text("CONVO_OK")
        await dispatcher.emit_done(
            session_id=str(kwargs.get("session_id") or ""),
            conversation_version=conversation.version,
            thinking_summary="canonical_v2",
            iterations=1,
            tool_calls=0,
            mode=str(kwargs.get("mode") or ""),
            autonomy_level=int(kwargs.get("autonomy_level") or 0),
        )
        return conversation


async def _no_background_delegation(*_args: Any, **_kwargs: Any) -> None:
    return None


class TestServerOrchestratorOnlyMode(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        os.environ["THOMAS_DB_PATH"] = f"{self._tmpdir.name}\\prefs_orch_only.sqlite"

    def tearDown(self) -> None:
        if self._prev_db_path is None:
            os.environ.pop("THOMAS_DB_PATH", None)
        else:
            os.environ["THOMAS_DB_PATH"] = self._prev_db_path
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

    async def _post(self, payload: dict[str, Any]):
        _FakeBrain.calls = []
        with (
            patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeBrain),
            patch("thomas.server.routes.chat_v2.start_background_delegation", _no_background_delegation),
        ):
            return await self.client.post("/api/chat", json=payload)

    async def test_non_task_chat_uses_the_canonical_v2_brain(self):
        resp = await self._post({"profile": "local", "mode": "fast", "text": "hey just chatting"})
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertEqual(resp.headers.get("X-Thomas-Chat-Engine"), "v2")
        self.assertTrue(any(event.get("type") == "done" for event in events))
        self.assertEqual(_FakeBrain.calls[0].get("mode"), "fast")

    async def test_explicit_swarm_mode_migrates_to_v2_max(self):
        resp = await self._post({"profile": "local", "mode": "swarm", "text": "run this in swarm mode"})
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        migrated = [event for event in events if event.get("type") == "mode_migrated"]
        self.assertEqual(migrated[0].get("from"), "swarm")
        self.assertEqual(migrated[0].get("to"), "max")
        self.assertEqual(_FakeBrain.calls[0].get("mode"), "max")

    async def test_l4_task_request_keeps_autonomy_on_the_v2_brain(self):
        resp = await self._post(
            {
                "profile": "local",
                "autonomy_level": 4,
                "text": "implement the endpoint and update the tests",
            }
        )
        self.assertEqual(resp.status, 200)
        await resp.text()
        call = _FakeBrain.calls[0]
        self.assertEqual(int(call.get("autonomy_level") or 0), 4)
        self.assertTrue(callable(call.get("send_task")))


if __name__ == "__main__":
    unittest.main()
