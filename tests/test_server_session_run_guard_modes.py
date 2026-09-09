"""Session-run-guard behaviour across chat modes.

Two requests for the SAME session must never run a turn concurrently --
concurrent turns can interleave conversation state.

History (2026-07-22): this suite previously sabotaged Chat V2 registration to
force a "legacy" chat route and mocked ``AgentLoop``. Both premises were dead:
``register_chat_routes`` is never called, so ``/api/chat`` is registered ONLY by
Chat V2 (sabotaging it made the endpoint 404), and Chat V2 drives
``OrchestratorBrain`` rather than ``AgentLoop``, so no patch target could work.
The suite therefore timed out rather than testing anything.

Migrating it to the real seam exposed a genuine defect: the session-run guard
had never been ported to Chat V2, so both requests executed concurrently. The
fix serialises turns per session (rather than rejecting the second and silently
dropping the user's message), which is what these tests now assert.
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


class _ConcurrencyProbeBrain:
    """Holds the first turn open and records how many turns overlap."""

    started: asyncio.Event | None = None
    release: asyncio.Event | None = None
    active = 0
    max_active = 0
    hold_prompt = ""

    @classmethod
    def reset(cls, hold_prompt: str) -> None:
        cls.started = asyncio.Event()
        cls.release = asyncio.Event()
        cls.active = 0
        cls.max_active = 0
        cls.hold_prompt = hold_prompt

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def process_message(self, *, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        _ = (session_id, dispatcher, kwargs)
        cls = type(self)
        cls.active += 1
        cls.max_active = max(cls.max_active, cls.active)
        try:
            if prompt == cls.hold_prompt and isinstance(cls.started, asyncio.Event):
                cls.started.set()
                if isinstance(cls.release, asyncio.Event):
                    await asyncio.wait_for(cls.release.wait(), timeout=10.0)
            return conversation
        finally:
            cls.active -= 1


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
        return create_app(cfg)

    async def _new_session_id(self) -> str:
        resp = await self.client.post("/api/session/new", json={})
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        return str(payload.get("session_id") or "")

    async def _assert_turns_do_not_overlap(self, sid: str, mode: str | None = None) -> None:
        first = {"session_id": sid, "text": "hold"}
        second = {"session_id": sid, "text": "follow-up"}
        if mode:
            first["mode"] = mode
            second["mode"] = mode

        _ConcurrencyProbeBrain.reset("hold")
        try:
            with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _ConcurrencyProbeBrain):
                first_task = asyncio.create_task(self.client.post("/api/chat", json=first))
                await asyncio.wait_for(_ConcurrencyProbeBrain.started.wait(), timeout=15.0)

                # Fire the second while the first is provably still inside its
                # turn, and give it a real chance to barge in.
                second_task = asyncio.create_task(self.client.post("/api/chat", json=second))
                await asyncio.sleep(0.75)

                self.assertEqual(
                    _ConcurrencyProbeBrain.max_active,
                    1,
                    "a second request executed a turn while the first was still running",
                )

                _ConcurrencyProbeBrain.release.set()
                first_resp = await first_task
                second_resp = await second_task

            self.assertEqual(first_resp.status, 200)
            self.assertEqual(second_resp.status, 200)
            self.assertEqual(_ConcurrencyProbeBrain.max_active, 1)
        finally:
            if isinstance(_ConcurrencyProbeBrain.release, asyncio.Event):
                _ConcurrencyProbeBrain.release.set()

    async def test_default_mode_path_enforces_session_run_guard(self):
        await self._assert_turns_do_not_overlap(await self._new_session_id())

    async def test_batch_mode_path_enforces_session_run_guard(self):
        await self._assert_turns_do_not_overlap(await self._new_session_id(), mode="batch")

    async def test_swarm_mode_path_enforces_session_run_guard(self):
        await self._assert_turns_do_not_overlap(await self._new_session_id(), mode="swarm")

    async def test_different_sessions_are_not_serialised_against_each_other(self):
        """The guard must be per-session, not a global chat bottleneck."""
        sid_a = await self._new_session_id()
        sid_b = await self._new_session_id()

        _ConcurrencyProbeBrain.reset("hold")
        try:
            with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _ConcurrencyProbeBrain):
                held = asyncio.create_task(self.client.post("/api/chat", json={"session_id": sid_a, "text": "hold"}))
                await asyncio.wait_for(_ConcurrencyProbeBrain.started.wait(), timeout=15.0)

                other = await self.client.post("/api/chat", json={"session_id": sid_b, "text": "other session"})
                self.assertEqual(other.status, 200)

                _ConcurrencyProbeBrain.release.set()
                self.assertEqual((await held).status, 200)
        finally:
            if isinstance(_ConcurrencyProbeBrain.release, asyncio.Event):
                _ConcurrencyProbeBrain.release.set()


if __name__ == "__main__":
    unittest.main()
