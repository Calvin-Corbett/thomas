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


class _FakeAgentLoopBadUsage:
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
        yield AgentEvent.text_delta("USAGE_BAD")
        yield AgentEvent.agent_done(
            text="USAGE_BAD",
            iterations=1,
            tool_calls=0,
            usage={"prompt_tokens": "9", "completion_tokens": -4, "total_tokens": 1},
            token_report={"mode": str(mode)},
        )


class _FakeAgentLoopNoUsage:
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
        yield AgentEvent.text_delta("USAGE_NONE")
        yield AgentEvent.agent_done(
            text="USAGE_NONE",
            iterations=1,
            tool_calls=0,
            usage=None,
            token_report={"mode": str(mode)},
        )


class TestServerUsageInvariants(AioHTTPTestCase):
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

    async def _new_session_id(self) -> str:
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)
        return sid

    async def test_done_usage_is_normalized_for_malformed_values(self):
        sid = await self._new_session_id()

        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopBadUsage):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "fast",
                    "text": "run",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)

        done = [e for e in events if e.get("type") == "done"][0]
        expected_run = {"prompt_tokens": 9, "completion_tokens": 0, "total_tokens": 9}
        self.assertEqual(done.get("usage"), expected_run)
        self.assertEqual(done.get("run_usage"), expected_run)

        session_usage = done.get("session_usage") or {}
        self.assertGreaterEqual(int(session_usage.get("prompt_tokens", 0)), 0)
        self.assertGreaterEqual(int(session_usage.get("completion_tokens", 0)), 0)
        self.assertGreaterEqual(int(session_usage.get("total_tokens", 0)), 0)

    async def test_done_usage_defaults_to_zero_when_missing(self):
        sid = await self._new_session_id()

        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopNoUsage):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "fast",
                    "text": "run",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)

        done = [e for e in events if e.get("type") == "done"][0]
        expected = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.assertEqual(done.get("usage"), expected)
        self.assertEqual(done.get("run_usage"), expected)
        self.assertEqual(done.get("session_usage"), expected)


if __name__ == "__main__":
    unittest.main()
