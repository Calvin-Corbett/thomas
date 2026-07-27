import json
import tempfile
import unittest
from types import SimpleNamespace
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


async def _fake_process_message(self, session_id, conversation, prompt, dispatcher, **_kwargs):  # noqa: ANN001
    conversation = conversation.append_message("user", prompt).append_message("assistant", "USAGE_CONTRACT_OK")
    self.llm.session_usage.add(TokenUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18))
    await dispatcher.emit_text("USAGE_CONTRACT_OK")
    await dispatcher.emit_done(
        session_id=session_id,
        conversation_version=conversation.version,
        iterations=1,
        tool_calls=0,
    )
    return conversation


async def _fake_process_malformed_usage(self, session_id, conversation, prompt, dispatcher, **_kwargs):  # noqa: ANN001
    conversation = conversation.append_message("user", prompt).append_message("assistant", "NORMALIZED_USAGE_OK")
    self.llm.session_usage = SimpleNamespace(
        prompt_tokens="9",
        completion_tokens=-4,
        total_tokens="not-a-number",
    )
    await dispatcher.emit_text("NORMALIZED_USAGE_OK")
    await dispatcher.emit_done(session_id=session_id, conversation_version=conversation.version)
    return conversation


async def _fake_process_missing_usage(self, session_id, conversation, prompt, dispatcher, **_kwargs):  # noqa: ANN001
    conversation = conversation.append_message("user", prompt).append_message("assistant", "MISSING_USAGE_OK")
    self.llm.session_usage = None
    await dispatcher.emit_text("MISSING_USAGE_OK")
    await dispatcher.emit_done(session_id=session_id, conversation_version=conversation.version)
    return conversation


class TestServerDoneUsageContract(AioHTTPTestCase):
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
                    model="local-model",
                )
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_standard_chat_done_has_run_and_session_usage(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        with patch("thomas.server.routes.chat_v2.OrchestratorBrain.process_message", _fake_process_message):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "fast",
                    "token_economy": "optimal",
                    "text": "run normal mode",
                },
            )
            response_body = await resp.text()

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(response_body)
        self.assertTrue(events)

        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        done = done_events[0]
        self.assertEqual(
            done.get("usage"),
            {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            events,
        )
        self.assertEqual(done.get("run_usage"), {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})
        session_usage = done.get("session_usage") or {}
        self.assertIn("prompt_tokens", session_usage)
        self.assertIn("completion_tokens", session_usage)
        self.assertIn("total_tokens", session_usage)
        seqs = [int(e.get("seq")) for e in events]
        self.assertTrue(all(v >= 0 for v in seqs))
        self.assertEqual(seqs, sorted(seqs))

    async def test_two_model_owned_turns_preserve_cumulative_session_usage(self):
        session_id = "usage-model-cumulative"
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain.process_message", _fake_process_message):
            seeded = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": session_id,
                    "profile": "local",
                    "mode": "fast",
                    "token_economy": "optimal",
                    "message": "seed provider usage",
                },
            )
            await seeded.read()
            response = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": session_id,
                    "profile": "local",
                    "mode": "fast",
                    "token_economy": "optimal",
                    "message": "continue the conversation",
                },
            )
            response_body = await response.text()

        self.assertEqual(seeded.status, 200)
        self.assertEqual(response.status, 200)
        done = [event for event in _parse_ndjson(response_body) if event.get("type") == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["usage"], {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})
        self.assertEqual(done[0]["run_usage"], {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})
        self.assertEqual(done[0]["session_usage"], {"prompt_tokens": 22, "completion_tokens": 14, "total_tokens": 36})

    async def test_malformed_and_missing_provider_usage_are_normalized(self):
        for index, (processor, expected) in enumerate(
            (
                (_fake_process_malformed_usage, {"prompt_tokens": 9, "completion_tokens": 0, "total_tokens": 9}),
                (_fake_process_missing_usage, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
            )
        ):
            session_id = f"usage-normalization-{index}"
            with patch("thomas.server.routes.chat_v2.OrchestratorBrain.process_message", processor):
                response = await self.client.post(
                    "/api/v2/chat",
                    json={
                        "session_id": session_id,
                        "profile": "local",
                        "mode": "fast",
                        "token_economy": "optimal",
                        "message": "normalize usage",
                    },
                )
                response_body = await response.text()
            self.assertEqual(response.status, 200)
            done = [event for event in _parse_ndjson(response_body) if event.get("type") == "done"]
            self.assertEqual(len(done), 1)
            self.assertEqual(done[0]["usage"], expected)
            self.assertEqual(done[0]["run_usage"], expected)
            self.assertEqual(done[0]["session_usage"], expected)


if __name__ == "__main__":
    unittest.main()
