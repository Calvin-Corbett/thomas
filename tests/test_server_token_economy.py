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


class _FakeAgentLoopTokenEconomy:
    last_mode: str | None = None
    last_max_iterations: int | None = None

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def run(  # noqa: ANN001
        self,
        prompt,
        *,
        mode="auto",
        tools_policy="auto",
        token_economy="optimal",
        max_iterations=None,
        job_type=None,
    ):
        _ = prompt
        _ = tools_policy
        _ = job_type
        _ = token_economy
        _FakeAgentLoopTokenEconomy.last_mode = str(mode)
        _FakeAgentLoopTokenEconomy.last_max_iterations = (
            int(max_iterations) if max_iterations is not None else None
        )
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
        yield AgentEvent.text_delta("TOKEN_ECONOMY_OK")
        yield AgentEvent.agent_done(
            text="TOKEN_ECONOMY_OK",
            iterations=1,
            tool_calls=0,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            token_report={"mode": str(mode)},
        )


class TestServerTokenEconomy(AioHTTPTestCase):
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
            max_agent_iterations=10,
        )
        return create_app(cfg)

    async def _new_session_id(self) -> str:
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)
        return sid

    async def test_max_profile_keeps_mode_and_raises_iteration_budget(self):
        sid = await self._new_session_id()
        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopTokenEconomy):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "fast",
                    "token_economy": "max",
                    "text": "run",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        route = [e for e in events if e.get("type") == "route"][0]
        self.assertEqual(str(route.get("mode") or ""), "fast")
        self.assertEqual(_FakeAgentLoopTokenEconomy.last_mode, "fast")
        self.assertIsNone(_FakeAgentLoopTokenEconomy.last_max_iterations)
        done = [e for e in events if e.get("type") == "done"][0]
        self.assertEqual((done.get("token_economy") or {}).get("applied"), "max")
        self.assertEqual(
            ((done.get("token_report") or {}).get("token_economy") or {}).get("applied"),
            "max",
        )

    async def test_cheap_profile_keeps_mode_and_lower_iteration_budget(self):
        sid = await self._new_session_id()
        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopTokenEconomy):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "thinking",
                    "token_economy": "cheap",
                    "text": "run",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        route = [e for e in events if e.get("type") == "route"][0]
        self.assertEqual(str(route.get("mode") or ""), "thinking")
        self.assertEqual(_FakeAgentLoopTokenEconomy.last_mode, "thinking")
        self.assertIsNone(_FakeAgentLoopTokenEconomy.last_max_iterations)
        done = [e for e in events if e.get("type") == "done"][0]
        self.assertEqual((done.get("token_economy") or {}).get("applied"), "cheap")

    async def test_optimal_profile_keeps_requested_mode_and_default_iterations(self):
        sid = await self._new_session_id()
        with patch("thomas.server.app.AgentLoop", _FakeAgentLoopTokenEconomy):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "auto",
                    "token_economy": "optimal",
                    "text": "run",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        route = [e for e in events if e.get("type") == "route"][0]
        self.assertEqual(str(route.get("mode") or ""), "auto")
        self.assertEqual(_FakeAgentLoopTokenEconomy.last_mode, "auto")
        self.assertIsNone(_FakeAgentLoopTokenEconomy.last_max_iterations)
        done = [e for e in events if e.get("type") == "done"][0]
        self.assertEqual((done.get("token_economy") or {}).get("applied"), "optimal")


if __name__ == "__main__":
    unittest.main()
