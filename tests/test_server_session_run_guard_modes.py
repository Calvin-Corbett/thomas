from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.events import AgentEvent, EventType
from thomas.server.app import create_app


class _BaseServerRunGuardCase(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    @property
    def _memory_root(self) -> str:
        return self._tmpdir.name


class _SlowAgentLoop:
    started: asyncio.Event | None = None
    release: asyncio.Event | None = None

    def __init__(self, *_args, **_kwargs):
        pass

    async def run(self, prompt, *, mode="auto", tools_policy="auto", token_economy="optimal", **kwargs):  # noqa: ANN001
        _ = prompt
        _ = token_economy
        _ = kwargs
        if isinstance(type(self).started, asyncio.Event):
            type(self).started.set()
        if isinstance(type(self).release, asyncio.Event):
            await asyncio.wait_for(type(self).release.wait(), timeout=2.0)
        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "route": {"path": "general", "confidence": 1.0},
                "mode": str(mode),
                "tools_policy": str(tools_policy),
                "autonomy_level": 3,
                "autonomy_name": "Auto",
            },
        )
        yield AgentEvent.agent_done(text="RUN_GUARD_OK", iterations=1, tool_calls=0)


class TestSessionRunGuardAcrossModes(_BaseServerRunGuardCase):
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
            memory=MemoryConfig(root=self._memory_root),
            server=ServerConfig(access_mode="local"),
        )
        with patch(
            "thomas.server.routes.chat_v2.register_chat_v2_routes", side_effect=RuntimeError("legacy-chat-required")
        ):
            return create_app(cfg)

    async def _new_session_id(self) -> str:
        resp = await self.client.post("/api/session/new", json={})
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        return str(payload.get("session_id") or "")

    async def _assert_second_request_conflicts(self, payload: dict, *, expected_second_status: int = 409) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        _SlowAgentLoop.started = started
        _SlowAgentLoop.release = release

        with patch("thomas.server.routes.chat_aiohttp.AgentLoop", _SlowAgentLoop):
            first_task = asyncio.create_task(self.client.post("/api/chat", json=payload))
            await asyncio.wait_for(started.wait(), timeout=2.0)
            second = await self.client.post("/api/chat", json=payload)
            self.assertEqual(second.status, expected_second_status)
            release.set()
            first = await first_task
            self.assertEqual(first.status, 200)

    async def test_default_mode_path_enforces_session_run_guard(self):
        sid = await self._new_session_id()
        payload = {"session_id": sid, "text": "default run"}
        await self._assert_second_request_conflicts(payload, expected_second_status=202)

    async def test_batch_mode_path_enforces_session_run_guard(self):
        sid = await self._new_session_id()
        payload = {"session_id": sid, "text": "batch run", "mode": "batch"}
        await self._assert_second_request_conflicts(payload, expected_second_status=202)

    async def test_swarm_mode_path_enforces_session_run_guard(self):
        sid = await self._new_session_id()
        payload = {"session_id": sid, "text": "swarm run", "mode": "swarm"}
        await self._assert_second_request_conflicts(payload, expected_second_status=202)


if __name__ == "__main__":
    unittest.main()
