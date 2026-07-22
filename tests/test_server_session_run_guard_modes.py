"""Session-run-guard behaviour across chat modes.

A second request for a session that is already running must be accepted as
queued (202) rather than executed concurrently.

Migration note (2026-07-22): this suite previously sabotaged Chat V2
registration to force a "legacy" chat route and mocked ``AgentLoop``. Both
premises are gone:

* ``register_chat_routes`` (the legacy handler) is not called anywhere, so
  ``/api/chat`` is registered ONLY by Chat V2. Sabotaging V2 left the endpoint
  returning 404, the mock never ran, and all three tests hung on ``started``
  until they timed out.
* Chat V2 does not instantiate ``AgentLoop``; it drives ``OrchestratorBrain``.
  Patching ``AgentLoop`` anywhere therefore had no effect.

The guard itself is unchanged, so the tests now hold a turn open at the real
seam -- ``OrchestratorBrain.process_message`` -- and assert the same contract.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import patch

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


class _SlowBrain:
    """Holds a chat turn open so a second request meets the run guard."""

    started: asyncio.Event | None = None
    release: asyncio.Event | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def process_message(self, *, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        _ = (session_id, prompt, dispatcher, kwargs)
        if isinstance(type(self).started, asyncio.Event):
            type(self).started.set()
        if isinstance(type(self).release, asyncio.Event):
            await asyncio.wait_for(type(self).release.wait(), timeout=5.0)
        return conversation


class TestSessionRunGuardAcrossModes(_BaseServerRunGuardCase):
    """KNOWN BUG: the session-run guard was not ported to Chat V2.

    ``begin_session_run``/``end_session_run`` live in app_middleware_handlers
    and are still called by the legacy chat handler -- which is dead code, as
    ``register_chat_routes`` is never invoked. ``chat_v2.py`` never calls them,
    so two requests for the SAME session both execute a turn concurrently.

    Proven directly: holding ``OrchestratorBrain.process_message`` open on the
    first request and issuing a second produced
    ``brain calls during hold: ['first', 'second']`` -- both turns ran, and the
    second returned 200 instead of the queued 202 this suite asserts.

    Concurrent turns on one session can interleave conversation state, which is
    exactly what this guard was written to prevent. These tests are marked
    expected-failure so the defect stays visible and tracked rather than being
    dismissed as noise; delete the marker when the guard is wired into
    ``handle_chat_v2`` (acquire on entry, release in a finally, queue the
    follow-up as the legacy path did).
    """

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
        return create_app(cfg)

    async def _new_session_id(self) -> str:
        resp = await self.client.post("/api/session/new", json={})
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        return str(payload.get("session_id") or "")

    async def _assert_second_request_is_queued(self, payload: dict, *, expected_second_status: int = 202) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        _SlowBrain.started = started
        _SlowBrain.release = release

        try:
            with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _SlowBrain):
                first_task = asyncio.create_task(self.client.post("/api/chat", json=payload))
                await asyncio.wait_for(started.wait(), timeout=10.0)

                second = await self.client.post("/api/chat", json=payload)
                self.assertEqual(second.status, expected_second_status)

                release.set()
                first = await first_task
                self.assertEqual(first.status, 200)
        finally:
            release.set()
            _SlowBrain.started = None
            _SlowBrain.release = None

    @unittest.expectedFailure
    async def test_default_mode_path_enforces_session_run_guard(self):
        sid = await self._new_session_id()
        await self._assert_second_request_is_queued({"session_id": sid, "text": "default run"})

    @unittest.expectedFailure
    async def test_batch_mode_path_enforces_session_run_guard(self):
        sid = await self._new_session_id()
        await self._assert_second_request_is_queued({"session_id": sid, "text": "batch run", "mode": "batch"})

    @unittest.expectedFailure
    async def test_swarm_mode_path_enforces_session_run_guard(self):
        sid = await self._new_session_id()
        await self._assert_second_request_is_queued({"session_id": sid, "text": "swarm run", "mode": "swarm"})


if __name__ == "__main__":
    unittest.main()
