import json
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.events import AgentEvent, EventType
from thomas.server.app import create_app


def _parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class _FakeAgentLoop:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def run(self, prompt, *, mode="auto", tools_policy="auto", job_type=None):  # noqa: ANN001
        _ = prompt
        _ = tools_policy
        _ = job_type
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "general", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": "never",
                "autonomy_level": 3,
                "autonomy_name": "Standard",
            },
        )
        yield AgentEvent.text_delta("USAGE_CONTRACT_OK")
        yield AgentEvent.agent_done(
            text="USAGE_CONTRACT_OK",
            iterations=1,
            tool_calls=0,
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            token_report={"mode": str(mode)},
        )


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
            models={"local": ModelConfig(name="local", model="dummy")},
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

        with patch("thomas.server.app.AgentLoop", _FakeAgentLoop):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "fast",
                    "text": "run normal mode",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)

        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        done = done_events[0]
        self.assertEqual(done.get("usage"), {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})
        self.assertEqual(done.get("run_usage"), {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})
        session_usage = done.get("session_usage") or {}
        self.assertIn("prompt_tokens", session_usage)
        self.assertIn("completion_tokens", session_usage)
        self.assertIn("total_tokens", session_usage)
        seqs = [int(e.get("seq")) for e in events]
        self.assertTrue(all(v >= 0 for v in seqs))
        self.assertEqual(seqs, sorted(seqs))

    async def test_ui_control_done_has_run_and_session_usage(self):
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)

        resp = await self.client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "profile": "local",
                "mode": "fast",
                "text": "please turn on tool details",
            },
        )
        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)

        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        done = done_events[0]
        self.assertEqual(done.get("usage"), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        self.assertEqual(done.get("run_usage"), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        self.assertEqual(done.get("session_usage"), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        self.assertEqual([int(e.get("seq")) for e in events], sorted(int(e.get("seq")) for e in events))


if __name__ == "__main__":
    unittest.main()
