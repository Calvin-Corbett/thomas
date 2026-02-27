import json
import os
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
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
            "final": "ORCHESTRATOR_ONLY_OK",
            "summary": {"status": {"t1": "done"}},
            "duration_ms": 5,
        }


class _AgentLoopShouldNotRun:
    initialized = False

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs
        _AgentLoopShouldNotRun.initialized = True

    async def run(self, *_args, **_kwargs):  # pragma: no cover - should never run
        raise AssertionError("AgentLoop must not run when orchestrator_only=true")


class _SwarmShouldNotRun:
    initialized = False

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs
        _SwarmShouldNotRun.initialized = True
        raise AssertionError("SwarmOrchestrator must not run for quick casual greetings")


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

    async def test_orchestrator_only_forces_swarm_and_skips_agent_loop(self):
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
                    "mode": "fast",
                    "orchestrator_only": True,
                    "text": "run this as orchestrator-only",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        swarm_done = [e for e in events if e.get("type") == "swarm_done"]
        self.assertEqual(len(swarm_done), 1)
        self.assertEqual(str(swarm_done[0].get("final") or ""), "ORCHESTRATOR_ONLY_OK")
        self.assertFalse(_AgentLoopShouldNotRun.initialized)

    async def test_orchestrator_only_returns_500_when_swarm_handler_returns_none(self):
        sid = await self._new_session_id()

        async def _no_swarm(*_args, **_kwargs):
            return None

        with patch("thomas.server.routes.chat_aiohttp.maybe_handle_swarm_mode", side_effect=_no_swarm):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "thinking",
                    "orchestrator_only": True,
                    "text": "force missing swarm",
                },
            )

        self.assertEqual(resp.status, 500)
        self.assertIn("orchestrator_only mode requires swarm orchestration", str(await resp.text()))

        with patch("thomas.server.swarm_mode.SwarmOrchestrator", _FakeSwarmOrchestrator):
            retry = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "thinking",
                    "orchestrator_only": True,
                    "text": "retry after failure",
                },
            )
        self.assertEqual(retry.status, 200)

    async def test_orchestrator_only_still_uses_quick_reply_for_simple_greeting(self):
        sid = await self._new_session_id()
        _SwarmShouldNotRun.initialized = False

        with patch("thomas.server.swarm_mode.SwarmOrchestrator", _SwarmShouldNotRun):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "orchestrator_only": True,
                    "text": "yo",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertFalse(_SwarmShouldNotRun.initialized)
        events = _parse_ndjson(await resp.text())
        text_events = [e for e in events if e.get("type") == "text"]
        self.assertTrue(text_events)
        self.assertIn("yo", str(text_events[-1].get("text") or "").lower())

    async def test_orchestrator_only_quick_reply_handles_user_request_prefix(self):
        sid = await self._new_session_id()
        _SwarmShouldNotRun.initialized = False

        with patch("thomas.server.swarm_mode.SwarmOrchestrator", _SwarmShouldNotRun):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "swarm",
                    "orchestrator_only": True,
                    "text": "Brainstorm mode\n\nUser request:\nyo",
                },
            )

        self.assertEqual(resp.status, 200)
        self.assertFalse(_SwarmShouldNotRun.initialized)
        events = _parse_ndjson(await resp.text())
        text_events = [e for e in events if e.get("type") == "text"]
        self.assertTrue(text_events)
        self.assertIn("yo", str(text_events[-1].get("text") or "").lower())


if __name__ == "__main__":
    unittest.main()
