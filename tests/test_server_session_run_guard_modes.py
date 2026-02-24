from __future__ import annotations

import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
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


class TestSessionRunGuardAcrossModes(_BaseServerRunGuardCase):
    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._memory_root),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def _new_session_id(self) -> str:
        resp = await self.client.post("/api/session/new", json={})
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        return str(payload.get("session_id") or "")

    async def _assert_second_request_conflicts(
        self,
        payload: dict,
        *,
        started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        first_task = asyncio.create_task(self.client.post("/api/chat", json=payload))
        await asyncio.wait_for(started.wait(), timeout=2.0)
        second = await self.client.post("/api/chat", json=payload)
        self.assertEqual(second.status, 409)
        release.set()
        first = await first_task
        self.assertEqual(first.status, 200)

    async def test_control_mode_path_enforces_session_run_guard(self):
        sid = await self._new_session_id()
        payload = {"session_id": sid, "text": "apply requested settings"}
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_control(*_args, **_kwargs):
            started.set()
            await asyncio.wait_for(release.wait(), timeout=2.0)
            return web.Response(status=200, text="control")

        control_req = SimpleNamespace(patch={}, operations=[], confirmation="ok")
        with (
            patch("thomas.server.app.resolve_ui_control_request", return_value=control_req),
            patch("thomas.server.app.handle_ui_control_chat", side_effect=_slow_control),
        ):
            await self._assert_second_request_conflicts(payload, started=started, release=release)

    async def test_batch_mode_path_enforces_session_run_guard(self):
        sid = await self._new_session_id()
        payload = {"session_id": sid, "text": "batch run", "mode": "batch"}
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_batch(*_args, **_kwargs):
            started.set()
            await asyncio.wait_for(release.wait(), timeout=2.0)
            return web.Response(status=200, text="batch")

        with (
            patch("thomas.server.app.model_supports", return_value=True),
            patch("thomas.server.app.handle_batch_mode_chat", side_effect=_slow_batch),
        ):
            await self._assert_second_request_conflicts(payload, started=started, release=release)

    async def test_swarm_mode_path_enforces_session_run_guard(self):
        sid = await self._new_session_id()
        payload = {"session_id": sid, "text": "swarm run", "mode": "swarm"}
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_swarm(*_args, **_kwargs):
            started.set()
            await asyncio.wait_for(release.wait(), timeout=2.0)
            return web.Response(status=200, text="swarm")

        class _DummySwarmSubagent:
            def __init__(self, *_args, **_kwargs):
                pass

        with (
            patch("thomas.server.app._LLMSwarmSubagent", _DummySwarmSubagent),
            patch("thomas.server.swarm_mode.handle_swarm_chat", side_effect=_slow_swarm),
        ):
            await self._assert_second_request_conflicts(payload, started=started, release=release)


if __name__ == "__main__":
    unittest.main()
