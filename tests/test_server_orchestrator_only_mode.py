import json
import os
import tempfile
import unittest
from typing import Any
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


class _FakeAgentLoopConversation:
    initialized = False
    captured: dict[str, Any] = {}

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        self._ctor_kwargs = dict(kwargs or {})
        _FakeAgentLoopConversation.initialized = True
        _FakeAgentLoopConversation.captured = {"ctor_kwargs": dict(self._ctor_kwargs)}

    async def run(self, prompt, *, mode="auto", tools_policy="auto", token_economy="optimal", **kwargs):  # noqa: ANN001
        _ = prompt
        _ = token_economy
        _FakeAgentLoopConversation.captured["run_kwargs"] = {
            "mode": str(mode),
            "tools_policy": str(tools_policy),
            **dict(kwargs or {}),
        }
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "casual_chat", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": str(tools_policy),
                "autonomy_level": int(self._ctor_kwargs.get("autonomy_level", 3) or 3),
                "autonomy_name": "Standard",
            },
        )
        yield AgentEvent.agent_done(
            text="CONVO_OK",
            iterations=1,
            tool_calls=0,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            token_report={"mode": str(mode)},
        )


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
        with patch(
            "thomas.server.routes.chat_v2.register_chat_v2_routes", side_effect=RuntimeError("legacy-chat-required")
        ):
            return create_app(cfg)

    async def _new_session_id(self) -> str:
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)
        return sid

    async def test_non_task_chat_defaults_to_agent_loop(self):
        _FakeAgentLoopConversation.initialized = False
        _FakeAgentLoopConversation.captured = {}
        sid = await self._new_session_id()

        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopConversation):
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
        self.assertTrue(_FakeAgentLoopConversation.initialized)

    async def test_explicit_swarm_mode_uses_agent_loop_with_normalized_mode(self):
        _FakeAgentLoopConversation.initialized = False
        _FakeAgentLoopConversation.captured = {}
        sid = await self._new_session_id()

        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopConversation):
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
        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        self.assertEqual(str(done_events[0].get("text") or ""), "CONVO_OK")
        self.assertTrue(_FakeAgentLoopConversation.initialized)
        run_kwargs = dict((_FakeAgentLoopConversation.captured or {}).get("run_kwargs") or {})
        self.assertEqual(str(run_kwargs.get("mode") or ""), "auto")

    async def test_l4_task_like_request_uses_agent_loop_and_keeps_autonomy(self):
        _FakeAgentLoopConversation.initialized = False
        _FakeAgentLoopConversation.captured = {}
        sid = await self._new_session_id()

        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _FakeAgentLoopConversation):
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
        route_events = [e for e in events if e.get("type") == "route"]
        self.assertEqual(len(route_events), 1)
        self.assertEqual(int(route_events[0].get("autonomy_level") or 0), 4)
        self.assertEqual(str(route_events[0].get("no_human_mode") or ""), "allow")
        self.assertTrue(_FakeAgentLoopConversation.initialized)


if __name__ == "__main__":
    unittest.main()
