"""Supervision of the agent worker: a stale first event, and user cancellation.

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


class TestWorkerSupervision(unittest.IsolatedAsyncioTestCase):
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

    async def test_supervised_agent_worker_fails_stale_first_event_from_web_loop(self):
        emitter = SimpleNamespace(failed=AsyncMock())

        async def _runner(*args, **kwargs):  # noqa: ANN001, ANN003
            await asyncio.sleep(0.05)

        stale_record = {
            "execution_id": "exec-native",
            "conversation_id": "sess-native",
            "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
            "state": "executing",
            "summary": "please implement this plan",
            "progress_summary": "Provider-native worker is running.",
            "last_heartbeat_at": "2000-01-01T00:00:00+00:00",
            "bot_id": "nova",
        }
        with (
            patch("thomas.server.chat_delegation._WORKER_FIRST_EVENT_TIMEOUT_S", 0.005),
            patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", return_value=stale_record),
            patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution") as fail_execution,
        ):
            await chat_delegation._run_agent_worker_supervised(
                _runner,
                {},
                execution_id="exec-native",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=self.repo_root,
                worker_kwargs={},
            )

        fail_execution.assert_called_once()
        self.assertEqual(fail_execution.call_args.kwargs["blocker"], "provider_native_timeout")
        emitter.failed.assert_awaited_once()

    async def test_supervised_agent_worker_terminalizes_user_cancellation_immediately(self):
        emitter = SimpleNamespace(failed=AsyncMock())

        async def _runner(*args, **kwargs):  # noqa: ANN001, ANN003
            await asyncio.sleep(10)

        running_record = {
            "execution_id": "exec-cancel",
            "conversation_id": "sess-cancel",
            "state": "executing",
            "summary": "long max task",
            "progress_summary": "Reviewing candidate answers.",
            "last_heartbeat_at": "2099-01-01T00:00:00+00:00",
            "bot_id": "nova",
        }
        with (
            patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", return_value=running_record),
            patch("thomas.server.chat_delegation.task_bot_runtime.is_cancel_requested", return_value=True),
            patch("thomas.server.chat_delegation.task_bot_runtime.cancel_execution") as cancel_execution,
        ):
            await chat_delegation._run_agent_worker_supervised(
                _runner,
                {},
                execution_id="exec-cancel",
                specialist_id="reasoning",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=self.repo_root,
                worker_kwargs={"effort": "max"},
            )

        # A stop is recorded as cancelled, NOT as a failure: filing it with
        # fail_execution made every deliberate Stop look like a crash in the
        # task list, with a failed proof beside it.
        cancel_execution.assert_called_once()
        emitter.failed.assert_awaited_once()
        self.assertEqual(emitter.failed.await_args.kwargs["text"], "Stopped by you.")
