"""Canvas routing: the model declares the surface, and dispatch honours it.

Split out of ``test_chat_delegation.py`` on 2026-09-20 to bring that file back
under the 800-line soft limit. These cases pin the rule that the surface comes
from a structured field, never from re-reading the wording of the prompt.
"""

import asyncio
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.chat_delegation_support import (  # noqa: F401
    _BotStub,
    _isolate_thomas_home,
    _model_runtime_event,
)
from thomas.server import chat_delegation, chat_delegation_runner


class TestCanvasRouting(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # A throwaway repo root per test. These cases used to pass
        # `repo_root=Path(".").resolve()`, and pytest runs from the checkout, so
        # that WAS the live repo: any unpatched `task_bot_runtime.update_execution`
        # wrote a real execution record into runtime/coordination/task_bots/ and
        # left it there. Mission Control reads that directory, so the leftovers
        # showed up as live agents in three later tests.
        self._repo_root_tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._repo_root_tmpdir.cleanup)
        self.repo_root = Path(self._repo_root_tmpdir.name).resolve()

    async def test_model_declared_canvas_is_honored_without_prompt_reclassification(self):
        emit_event = AsyncMock()
        canvas_record = {"execution_id": "exec-canvas"}
        with (
            patch("thomas.server.chat_delegation.pick_bot_for_specialist", return_value=_BotStub()),
            patch(
                "thomas.server.chat_delegation._start_canvas_worker_delegation",
                new=AsyncMock(return_value=canvas_record),
            ) as start_canvas,
            patch(
                "thomas.server.chat_delegation._start_agent_worker_delegation",
                new=AsyncMock(),
            ) as start_agent,
        ):
            result = await chat_delegation.start_background_delegation(
                {},
                session_id="sess-ordinary",
                prompt="Explain why the sky looks blue in two sentences.",
                mode="auto",
                recent_messages=[],
                emit_event=emit_event,
                force=True,
                surface="canvas",
            )

        self.assertEqual(result, canvas_record)
        start_canvas.assert_awaited_once()
        start_agent.assert_not_awaited()

    async def test_model_declared_canvas_receives_structured_read_only_policy(self):
        emit_event = AsyncMock()
        canvas_record = {"execution_id": "exec-canvas", "state": "executing"}
        with (
            patch("thomas.server.chat_delegation.pick_bot_for_specialist", return_value=_BotStub()),
            patch(
                "thomas.server.chat_delegation._start_canvas_worker_delegation",
                new=AsyncMock(return_value=canvas_record),
            ) as start_canvas,
            patch(
                "thomas.server.chat_delegation._start_agent_worker_delegation",
                new=AsyncMock(),
            ) as start_agent,
        ):
            result = await chat_delegation.start_background_delegation(
                {},
                session_id="sess-read-only-canvas",
                prompt="Build a playable browser game.",
                mode="auto",
                recent_messages=[],
                emit_event=emit_event,
                force=True,
                file_access=0,
                surface="canvas",
            )

        self.assertEqual(result, canvas_record)
        start_canvas.assert_awaited_once()
        self.assertEqual(start_canvas.await_args.kwargs["file_access"], 0)
        start_agent.assert_not_awaited()

    async def test_canvas_worker_receives_selected_profile(self):
        emit_event = AsyncMock()
        canvas_record = {"execution_id": "exec-canvas"}
        with (
            patch("thomas.server.chat_delegation.pick_bot_for_specialist", return_value=_BotStub()),
            patch(
                "thomas.server.chat_delegation._start_canvas_worker_delegation",
                new=AsyncMock(return_value=canvas_record),
            ) as start_canvas,
            patch(
                "thomas.server.chat_delegation._start_agent_worker_delegation",
                new=AsyncMock(),
            ) as start_agent,
        ):
            result = await chat_delegation.start_background_delegation(
                {},
                session_id="sess-canvas-profile",
                prompt="Create an interactive quarterly revenue chart with tooltips.",
                mode="auto",
                recent_messages=[],
                emit_event=emit_event,
                force=True,
                profile="openai_codex",
                surface="canvas",
            )

        self.assertEqual(result, canvas_record)
        start_canvas.assert_awaited_once()
        self.assertEqual(start_canvas.await_args.kwargs["profile"], "openai_codex")
        start_agent.assert_not_awaited()
