import json
import os
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


class _FakeSwarmOrchestrator:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def astream(self, *, user_request, subagents):  # noqa: ANN001
        _ = user_request
        _ = subagents
        yield {
            "type": "swarm_done",
            "ok": True,
            "final": "SWARM_OK",
            "summary": {"status": {"t1": "done"}},
            "duration_ms": 5,
        }


class _FakeAgentLoopConversation:
    initialized = False

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs
        _FakeAgentLoopConversation.initialized = True

    async def run(self, prompt, *, mode="auto", tools_policy="auto", token_economy="optimal", **kwargs):  # noqa: ANN001
        _ = prompt
        _ = tools_policy
        _ = token_economy
        _ = kwargs
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "casual_chat", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": "never",
                "autonomy_level": 3,
                "autonomy_name": "Standard",
            },
        )
        yield AgentEvent.text_delta("CONVO_OK")
        yield AgentEvent.agent_done(
            text="CONVO_OK",
            iterations=1,
            tool_calls=0,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            token_report={"mode": str(mode)},
        )


class _AgentLoopShouldNotRun:
    initialized = False

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs
        _AgentLoopShouldNotRun.initialized = True

    async def run(self, *_args, **_kwargs):  # pragma: no cover - should never run
        raise AssertionError("AgentLoop must not run when swarm orchestration is selected")


class TestServerOrchestratorOnlyMode(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._prev_db_path = os.environ.get("THOMAS_DB_PATH")
        self._db_path = f"{self._tmpdir.name}\\prefs_orch_only.sqlite"
        os.environ["THOMAS_DB_PATH"] = self._db_path

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

    async def test_non_task_chat_defaults_to_agent_loop(self):
        _FakeAgentLoopConversation.initialized = False
        sid = await self._new_session_id()

        with (
            patch("thomas.server.swarm_mode.SwarmOrchestrator", _FakeSwarmOrchestrator),
            patch("thomas.server.app.AgentLoop", _FakeAgentLoopConversation),
        ):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "fast",
                    "text": "hey just chatting",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        self.assertEqual(str(done_events[0].get("text") or ""), "CONVO_OK")
        self.assertEqual([e for e in events if e.get("type") == "swarm_done"], [])
        self.assertTrue(_FakeAgentLoopConversation.initialized)

    async def test_explicit_swarm_mode_skips_agent_loop(self):
        _AgentLoopShouldNotRun.initialized = False
        sid = await self._new_session_id()

        with (
            patch("thomas.server.swarm_mode.SwarmOrchestrator", _FakeSwarmOrchestrator),
            patch("thomas.server.app.AgentLoop", _AgentLoopShouldNotRun),
        ):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "text": "run this in swarm mode",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        swarm_done = [e for e in events if e.get("type") == "swarm_done"]
        self.assertEqual(len(swarm_done), 1)
        self.assertEqual(str(swarm_done[0].get("final") or ""), "SWARM_OK")
        self.assertFalse(_AgentLoopShouldNotRun.initialized)

    async def test_l4_task_like_request_auto_routes_to_swarm(self):
        _AgentLoopShouldNotRun.initialized = False
        sid = await self._new_session_id()

        with (
            patch("thomas.server.swarm_mode.SwarmOrchestrator", _FakeSwarmOrchestrator),
            patch("thomas.server.app.AgentLoop", _AgentLoopShouldNotRun),
        ):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "autonomy_level": 4,
                    "text": "implement the endpoint and update the tests",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        swarm_done = [e for e in events if e.get("type") == "swarm_done"]
        self.assertEqual(len(swarm_done), 1)
        self.assertEqual(str(swarm_done[0].get("final") or ""), "SWARM_OK")
        self.assertFalse(_AgentLoopShouldNotRun.initialized)

    async def test_explicit_swarm_returns_500_when_swarm_handler_returns_none(self):
        sid = await self._new_session_id()

        async def _no_swarm(*_args, **_kwargs):
            return None

        with patch("thomas.server.routes.chat_aiohttp.maybe_handle_swarm_mode", side_effect=_no_swarm):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "text": "force missing swarm",
                },
            )

        self.assertEqual(resp.status, 500)
        self.assertIn("specialist orchestration is required", str(await resp.text()))


if __name__ == "__main__":
    unittest.main()
