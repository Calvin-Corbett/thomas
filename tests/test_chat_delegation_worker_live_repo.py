"""Live-repo runs: the heartbeat before baseline, and proof a file really changed.

Split out of ``test_chat_delegation.py`` on 2026-09-20. That file had reached
1676 lines, past the 1200-line hard limit, and the monolith guard only fires on
a file you touch -- so it sat in violation until a one-line change needed to go
in. The growth guard then caps any single file at +300 lines per commit, which
is why the worker cases are four focused modules rather than one large one.
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
from thomas.server import chat_delegation, chat_delegation_runner  # noqa: F401


class TestWorkerLiveRepo(unittest.IsolatedAsyncioTestCase):
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

    async def test_run_agent_worker_heartbeats_before_live_repo_baseline(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        fail_called = False
        saw_baseline = False

        async def _events():  # noqa: ANN202
            yield {"type": "error", "error": "stop after baseline"}

        def _workspace_mtimes(_path, **kwargs):  # noqa: ANN202
            nonlocal saw_baseline
            saw_baseline = True
            self.assertIn("runtime/", kwargs.get("ignored_prefixes", ()))
            self.assertIn("node_modules", kwargs.get("ignored_parts", frozenset()))
            self.assertEqual(emitter.progress.await_count, 1)
            self.assertEqual(
                emitter.progress.await_args_list[0].kwargs["text"],
                "Preparing private copy change baseline.",
            )
            return {}

        def _fail_execution(*_args, **_kwargs):  # noqa: ANN202
            nonlocal fail_called
            fail_called = True
            return None

        def _get_execution(*_args, **_kwargs):  # noqa: ANN202
            return {
                "execution_id": "exec-native",
                "conversation_id": "sess-native",
                "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                "state": "failed" if fail_called else "executing",
                "summary": "Modify Thomas.",
                "progress_summary": "Background execution failed: stop after baseline",
                "bot_id": "nova",
            }

        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            with (
                patch(
                    "thomas.server.chat_delegation.run_agent_worker_events",
                    new=lambda *args, **kwargs: _events(),  # noqa: ARG005
                ),
                patch("thomas.server.chat_delegation._workspace_mtimes", side_effect=_workspace_mtimes),
                patch(
                    "thomas.server.chat_delegation.task_bot_runtime.fail_execution",
                    side_effect=_fail_execution,
                ),
                patch("thomas.server.chat_delegation.task_bot_runtime.update_execution"),
                patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", side_effect=_get_execution),
            ):
                await chat_delegation._run_agent_worker(
                    {},
                    execution_id="exec-native",
                    prompt="Modify Thomas.",
                    specialist_id="coding",
                    bot=_BotStub(),
                    emitter=emitter,
                    instructions="Do live repo work.",
                    repo_root=root,
                    work_dir=root,
                    requires_live_repo_change=True,
                    autonomy_level=1,
                )

        self.assertTrue(saw_baseline)
        emitter.failed.assert_awaited_once()
        emitter.completed.assert_not_awaited()

    async def test_run_agent_worker_live_repo_requires_changed_file(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        captured = {}

        async def _events():  # noqa: ANN202
            yield _model_runtime_event()
            yield {"type": "tool_start", "name": "shell.exec"}
            yield {"type": "tool_output", "name": "shell.exec", "ok": True}
            yield {"type": "done"}

        def _worker_events(*_args, **kwargs):  # noqa: ANN202
            captured["prompt"] = kwargs["prompt"]
            return _events()

        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            fail_called = False

            def _fail_execution(*_args, **_kwargs):  # noqa: ANN202
                nonlocal fail_called
                fail_called = True
                return None

            def _get_execution(*_args, **_kwargs):  # noqa: ANN202
                return {
                    "execution_id": "exec-native",
                    "conversation_id": "sess-native",
                    "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                    "state": "failed" if fail_called else "executing",
                    "summary": "Modify Thomas.",
                    "progress_summary": "self-development task changed no live repo files",
                    "bot_id": "nova",
                }

            with (
                patch(
                    "thomas.server.chat_delegation.run_agent_worker_events",
                    new=_worker_events,
                ),
                patch("thomas.server.chat_delegation.task_bot_runtime.update_execution"),
                patch(
                    "thomas.server.chat_delegation.task_bot_runtime.fail_execution",
                    side_effect=_fail_execution,
                ) as fail_execution,
                patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", side_effect=_get_execution),
            ):
                await chat_delegation._run_agent_worker(
                    {},
                    execution_id="exec-native",
                    prompt="Modify Thomas.",
                    specialist_id="coding",
                    bot=_BotStub(),
                    emitter=emitter,
                    instructions="Do live repo work.",
                    repo_root=root,
                    work_dir=root,
                    requires_live_repo_change=True,
                    autonomy_level=1,
                )

        fail_execution.assert_called_once()
        self.assertIn("LIVE REPO COMPLETION REQUIREMENT:", captured["prompt"])
        self.assertTrue(
            "Ignored/generated files" in captured["prompt"] or "Pure inspection does not count" in captured["prompt"]
        )
        self.assertIn("fs.write_file", captured["prompt"])
        self.assertIn("no live repo files", fail_execution.call_args.kwargs["summary"])
        emitter.failed.assert_awaited_once()
        emitter.completed.assert_not_awaited()

    async def test_run_agent_worker_live_repo_retry_mentions_missing_write_tool(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        prompts: list[str] = []

        async def _events():  # noqa: ANN202
            yield _model_runtime_event()
            yield {"type": "tool_start", "name": "shell.exec"}
            yield {"type": "tool_output", "name": "shell.exec", "ok": True}
            yield {"type": "done"}

        def _worker_events(*_args, **kwargs):  # noqa: ANN202
            prompts.append(kwargs["prompt"])
            return _events()

        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            fail_called = False

            def _fail_execution(*_args, **_kwargs):  # noqa: ANN202
                nonlocal fail_called
                fail_called = True
                return None

            def _get_execution(*_args, **_kwargs):  # noqa: ANN202
                return {
                    "execution_id": "exec-native",
                    "conversation_id": "sess-native",
                    "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                    "state": "failed" if fail_called else "executing",
                    "summary": "Modify Thomas.",
                    "progress_summary": "self-development task changed no live repo files",
                    "bot_id": "nova",
                }

            with (
                patch("thomas.server.chat_delegation.run_agent_worker_events", new=_worker_events),
                patch("thomas.server.chat_delegation.task_bot_runtime.update_execution"),
                patch(
                    "thomas.server.chat_delegation.task_bot_runtime.fail_execution",
                    side_effect=_fail_execution,
                ) as fail_execution,
                patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", side_effect=_get_execution),
            ):
                await chat_delegation._run_agent_worker(
                    {},
                    execution_id="exec-native",
                    prompt="Modify Thomas.",
                    specialist_id="coding",
                    bot=_BotStub(),
                    emitter=emitter,
                    instructions="Do live repo work.",
                    repo_root=root,
                    work_dir=root,
                    requires_live_repo_change=True,
                    autonomy_level=4,
                )

        self.assertEqual(len(prompts), 3)
        self.assertIn("LIVE REPO COMPLETION REQUIREMENT:", prompts[0])
        self.assertIn("no write tool was used", prompts[1])
        self.assertIn("Stop broad inspection now", prompts[1])
        self.assertIn("next substantive tool call must be diff.create", prompts[1])
        self.assertIn("prefer a small regression test or catalog policy edit", prompts[1])
        self.assertIn("Stop broad inspection now", prompts[2])
        self.assertIn("next substantive tool call must be diff.create", prompts[2])
        self.assertIn("fs.write_file", prompts[1])
        self.assertIn("no write tool was used", fail_execution.call_args.kwargs["summary"])
        emitter.failed.assert_awaited_once()
        emitter.completed.assert_not_awaited()
