"""When the worker does not finish: a reported failure, silence, and cancellation.

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


class TestWorkerFailures(unittest.IsolatedAsyncioTestCase):
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

    async def test_run_agent_worker_reports_failure(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        fail_called = False

        async def _events():  # noqa: ANN202
            yield {"type": "error", "error": "worker exploded"}

        def _fail_execution(*_args, **_kwargs):  # noqa: ANN202
            nonlocal fail_called
            fail_called = True
            return None

        real_get_execution = chat_delegation.task_bot_runtime.get_execution

        def _get_execution(execution_id="exec-native", repo_root=None, *_args, **_kwargs):  # noqa: ANN202
            # Overlay the real record so the revision the runtime wrote survives: update_execution refuses to
            # write over a record whose revision changed on disk after it was read, and a made-up record with
            # no revision looks like a second writer.
            real = real_get_execution(execution_id, repo_root) or {}
            return {
                **real,
                "execution_id": "exec-native",
                "conversation_id": "sess-native",
                "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                "state": "failed" if fail_called else "executing",
                "summary": "please implement this plan",
                "progress_summary": "Background execution failed: worker exploded",
                "bot_id": "nova",
            }

        with (
            patch(
                "thomas.server.chat_delegation.run_agent_worker_events",
                new=lambda *args, **kwargs: _events(),  # noqa: ARG005
            ),
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.fail_execution",
                side_effect=_fail_execution,
            ) as fail_execution,
            patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", side_effect=_get_execution),
        ):
            await chat_delegation._run_agent_worker(
                {},
                execution_id="exec-native",
                prompt="please implement this plan",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                instructions="Do the work.",
                repo_root=self.repo_root,
            )

        fail_execution.assert_called_once()
        failure_summary = str(fail_execution.call_args.kwargs["summary"])
        self.assertIn("provider-native worker reported a retryable error", failure_summary)
        self.assertNotIn("worker exploded", failure_summary)
        emitter.failed.assert_awaited_once()
        emitter.completed.assert_not_awaited()

    async def test_run_agent_worker_fails_when_first_event_never_arrives(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

        async def _events():  # noqa: ANN202
            await asyncio.sleep(0.05)
            yield {"type": "done"}

        with (
            patch(
                "thomas.server.chat_delegation.run_agent_worker_events",
                new=lambda *args, **kwargs: _events(),  # noqa: ARG005
            ),
            patch("thomas.server.chat_delegation._WORKER_FIRST_EVENT_TIMEOUT_S", 0.005),
            patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution") as fail_execution,
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.get_execution",
                return_value={
                    "execution_id": "exec-native",
                    "conversation_id": "sess-native",
                    "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                    "state": "failed",
                    "summary": "please implement this plan",
                    "progress_summary": "Background execution failed: provider-native worker produced no first event",
                    "bot_id": "nova",
                },
            ),
        ):
            await chat_delegation._run_agent_worker(
                {},
                execution_id="exec-native",
                prompt="please implement this plan",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                instructions="Do the work.",
                repo_root=self.repo_root,
                autonomy_level=1,
            )

        fail_execution.assert_called_once()
        self.assertIn("produced no first event", fail_execution.call_args.kwargs["summary"])
        emitter.failed.assert_awaited_once()
        emitter.completed.assert_not_awaited()

    async def test_run_agent_worker_marks_cancellation_and_propagates(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

        async def _events():  # noqa: ANN202
            for _ in range(0):
                yield {}  # makes this an async generator without yielding
            raise asyncio.CancelledError

        with (
            patch(
                "thomas.server.chat_delegation.run_agent_worker_events",
                new=lambda *args, **kwargs: _events(),  # noqa: ARG005
            ),
            patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution") as fail_execution,
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.get_execution",
                return_value={"execution_id": "exec-c", "bot_id": "nova"},
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await chat_delegation._run_agent_worker(
                    {},
                    execution_id="exec-c",
                    prompt="x",
                    specialist_id="coding",
                    bot=_BotStub(),
                    emitter=emitter,
                    instructions="do",
                    repo_root=self.repo_root,
                )

        fail_execution.assert_called_once()
        self.assertEqual(fail_execution.call_args.kwargs.get("blocker"), "cancelled")
        emitter.failed.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
