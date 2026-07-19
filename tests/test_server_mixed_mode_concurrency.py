import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.llm import TokenUsage
from thomas.server.app import create_app


def _parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


async def _fake_process_message(self, session_id, conversation, prompt, dispatcher, *, mode="auto", **_kwargs):  # noqa: ANN001
    text = f"{mode.upper()}_CONCURRENT_OK"
    conversation = conversation.append_message("user", prompt).append_message("assistant", text)
    self.llm.session_usage.add(TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5))
    await dispatcher.emit({"type": "route", "route": {"path": "general"}, "mode": mode})
    await asyncio.sleep(0.01)
    await dispatcher.emit_text(text)
    await dispatcher.emit_done(session_id=session_id, conversation_version=conversation.version)
    return conversation


class TestServerMixedModeConcurrency(AioHTTPTestCase):
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
                "xai": ModelConfig(
                    name="xai",
                    provider="openai_compat",
                    base_url="https://api.x.ai/v1",
                    api_key="test-key",
                    model="grok-4-1-fast-reasoning",
                    timeout_s=1,
                ),
                "local": ModelConfig(name="local", model="dummy"),
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def _new_session_id(self) -> str:
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)
        return sid

    async def test_thinking_and_fast_streams_are_isolated_under_concurrency(self):
        sid_fast = await self._new_session_id()
        sid_thinking = await self._new_session_id()

        async def _call_fast():
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid_fast,
                    "profile": "local",
                    "mode": "fast",
                    "text": "run fast",
                },
            )
            return resp.status, _parse_ndjson(await resp.text())

        async def _call_thinking():
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid_thinking,
                    "profile": "xai",
                    "mode": "thinking",
                    "text": "run thinking",
                },
            )
            return resp.status, _parse_ndjson(await resp.text())

        with patch("thomas.server.routes.chat_v2.OrchestratorBrain.process_message", _fake_process_message):
            (fast_status, fast_events), (thinking_status, thinking_events) = await asyncio.gather(
                _call_fast(),
                _call_thinking(),
            )

        self.assertEqual(fast_status, 200)
        self.assertEqual(thinking_status, 200)
        self.assertTrue(fast_events)
        self.assertTrue(thinking_events)

        fast_run_ids = {str(e.get("run_id") or "") for e in fast_events if e.get("run_id")}
        thinking_run_ids = {str(e.get("run_id") or "") for e in thinking_events if e.get("run_id")}
        self.assertEqual(len(fast_run_ids), 1)
        self.assertEqual(len(thinking_run_ids), 1)
        self.assertTrue(fast_run_ids.isdisjoint(thinking_run_ids))

        fast_text = [e for e in fast_events if e.get("type") == "text"]
        thinking_text = [e for e in thinking_events if e.get("type") == "text"]
        self.assertTrue(any("FAST_CONCURRENT_OK" in str(e.get("text") or "") for e in fast_text))
        self.assertTrue(any("THINKING_CONCURRENT_OK" in str(e.get("text") or "") for e in thinking_text))

        fast_route = [e for e in fast_events if e.get("type") == "route"]
        thinking_route = [e for e in thinking_events if e.get("type") == "route"]
        self.assertEqual(len(fast_route), 1)
        self.assertEqual(len(thinking_route), 1)
        self.assertEqual(str(fast_route[0].get("mode") or ""), "fast")
        self.assertEqual(str(thinking_route[0].get("mode") or ""), "thinking")

        fast_done = [e for e in fast_events if e.get("type") == "done"]
        thinking_done = [e for e in thinking_events if e.get("type") == "done"]
        self.assertEqual(len(fast_done), 1)
        self.assertEqual(len(thinking_done), 1)
        for done in (fast_done[0], thinking_done[0]):
            self.assertIn("usage", done)
            self.assertIn("run_usage", done)
            self.assertIn("session_usage", done)


if __name__ == "__main__":
    unittest.main()
