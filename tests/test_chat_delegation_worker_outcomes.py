"""What the worker reports at the end: completion, failure, silence, cancellation.

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


class TestWorkerOutcomes(unittest.IsolatedAsyncioTestCase):
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

    async def test_run_agent_worker_live_repo_ignores_generated_test_result_log(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            result_log = root / "thomas_test_results.jsonl"
            fail_called = False

            async def _events():  # noqa: ANN202
                result_log.write_text('{"ok": true}\n', encoding="utf-8")
                yield _model_runtime_event()
                yield {"type": "tool_start", "name": "shell.exec"}
                yield {"type": "tool_output", "name": "shell.exec", "ok": True}
                yield {"type": "done"}

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
                    new=lambda *args, **kwargs: _events(),  # noqa: ARG005
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
        self.assertIn("no live repo files", fail_execution.call_args.kwargs["summary"])
        emitter.failed.assert_awaited_once()
        emitter.completed.assert_not_awaited()

    async def test_run_agent_worker_live_repo_completion_reports_changed_file(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            target = root / "tests" / "self_dev_probe.txt"
            complete_called = False

            async def _events():  # noqa: ANN202
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("changed", encoding="utf-8")
                yield _model_runtime_event()
                yield {"type": "tool_start", "name": "fs.write_file"}
                yield {"type": "tool_output", "name": "fs.write_file", "ok": True}
                yield {"type": "done"}

            def _complete_execution(*_args, **_kwargs):  # noqa: ANN202
                nonlocal complete_called
                complete_called = True
                return None

            def _get_execution(*_args, **_kwargs):  # noqa: ANN202
                return {
                    "execution_id": "exec-native",
                    "conversation_id": "sess-native",
                    "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                    "state": "completed" if complete_called else "executing",
                    "summary": "Modify Thomas.",
                    "progress_summary": "Changed live Thomas files: tests/self_dev_probe.txt.",
                    "bot_id": "nova",
                }

            with (
                patch(
                    "thomas.server.chat_delegation.run_agent_worker_events",
                    new=lambda *args, **kwargs: _events(),  # noqa: ARG005
                ),
                patch("thomas.server.chat_delegation.task_bot_runtime.update_execution"),
                patch("thomas.server.chat_delegation.task_bot_runtime.attach_proof"),
                patch(
                    "thomas.server.chat_delegation.task_bot_runtime.complete_execution",
                    side_effect=_complete_execution,
                ) as complete_execution,
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

        complete_execution.assert_called_once()
        self.assertTrue(complete_execution.call_args.kwargs["verified_success"])
        emitter.completed.assert_awaited_once()
        emitter.failed.assert_not_awaited()

    async def test_run_agent_worker_live_repo_does_not_classify_docs_from_prompt(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            target = root / "docs" / "self_development" / "note.md"
            fail_called = False
            complete_called = False

            async def _events():  # noqa: ANN202
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("documented instead of fixed", encoding="utf-8")
                yield _model_runtime_event()
                yield {"type": "tool_start", "name": "fs.write_file"}
                yield {"type": "tool_output", "name": "fs.write_file", "ok": True}
                yield {"type": "done"}

            def _fail_execution(*_args, **_kwargs):  # noqa: ANN202
                nonlocal fail_called
                fail_called = True
                return None

            def _complete_execution(*_args, **_kwargs):  # noqa: ANN202
                nonlocal complete_called
                complete_called = True
                return {"execution_id": "exec-native", "state": "completed", "proof_status": "verified"}

            def _get_execution(*_args, **_kwargs):  # noqa: ANN202
                return {
                    "execution_id": "exec-native",
                    "conversation_id": "sess-native",
                    "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                    "state": "failed" if fail_called else ("completed" if complete_called else "executing"),
                    "summary": "Fix route and tests.",
                    "progress_summary": "self-development task changed only documentation files",
                    "bot_id": "nova",
                }

            with (
                patch(
                    "thomas.server.chat_delegation.run_agent_worker_events",
                    new=lambda *args, **kwargs: _events(),  # noqa: ARG005
                ),
                patch("thomas.server.chat_delegation.task_bot_runtime.update_execution"),
                patch(
                    "thomas.server.chat_delegation.task_bot_runtime.fail_execution",
                    side_effect=_fail_execution,
                ) as fail_execution,
                patch("thomas.server.chat_delegation.task_bot_runtime.attach_proof"),
                patch(
                    "thomas.server.chat_delegation.task_bot_runtime.complete_execution",
                    side_effect=_complete_execution,
                ) as complete_execution,
                patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", side_effect=_get_execution),
            ):
                await chat_delegation._run_agent_worker(
                    {},
                    execution_id="exec-native",
                    prompt="Fix the marketplace API route and focused tests.",
                    specialist_id="coding",
                    bot=_BotStub(),
                    emitter=emitter,
                    instructions="Do live repo work.",
                    repo_root=root,
                    work_dir=root,
                    requires_live_repo_change=True,
                    autonomy_level=1,
                )

        fail_execution.assert_not_called()
        complete_execution.assert_called_once()
        emitter.completed.assert_awaited_once()
        emitter.failed.assert_not_awaited()
