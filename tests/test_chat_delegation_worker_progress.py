"""The worker's progress, completion, and its model-runtime receipt.

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


class TestWorkerProgress(unittest.IsolatedAsyncioTestCase):
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

    async def test_run_agent_worker_reports_progress_and_completion(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        worker_call: dict[str, object] = {}

        async def _events():  # noqa: ANN202
            yield _model_runtime_event(model="gpt-5.6-terra")
            yield {"type": "progress", "text": "Provider-native worker is initializing."}
            yield {"type": "tool_start", "name": "grep"}
            yield {"type": "tool_output"}
            yield {"type": "text", "text": "Implemented the requested plan with verified configuration details."}
            yield {"type": "done"}

        def _worker_events(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            worker_call.update(kwargs)
            return _events()

        complete_called = False

        def _get_execution(*_args, **_kwargs):  # noqa: ANN202
            state = "completed" if complete_called else "executing"
            return {
                "execution_id": "exec-native",
                "conversation_id": "sess-native",
                "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                "state": state,
                "summary": "please implement this plan",
                "progress_summary": "Completed a tool step.",
                "bot_id": "nova",
            }

        def _complete_execution(*_args, **_kwargs):  # noqa: ANN202
            nonlocal complete_called
            complete_called = True
            return None

        with (
            patch(
                "thomas.server.chat_delegation.run_agent_worker_events",
                new=_worker_events,
            ),
            patch("thomas.server.chat_delegation.task_bot_runtime.update_execution") as update_execution,
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.complete_execution",
                side_effect=_complete_execution,
            ) as complete_execution,
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
                model_id="gpt-5.6-terra",
                reasoning_effort="max",
            )

        self.assertEqual(update_execution.call_count, 5)
        runtime_updates = [
            call.kwargs["runtime_profile"]
            for call in update_execution.call_args_list
            if "runtime_profile" in call.kwargs
        ]
        self.assertEqual(len(runtime_updates), 1)
        self.assertNotRegex(str(runtime_updates[0]), r"sk-never-persist|user:pass|raw provider error|token=secret")
        complete_execution.assert_called_once()
        self.assertEqual(emitter.progress.await_count, 4)
        self.assertEqual(emitter.progress.await_args_list[0].kwargs["text"], "Preparing workspace change baseline.")
        self.assertEqual(emitter.progress.await_args_list[1].kwargs["text"], "Provider-native worker is initializing.")
        self.assertEqual(worker_call["model_id"], "gpt-5.6-terra")
        self.assertEqual(worker_call["reasoning_effort"], "max")
        emitter.completed.assert_awaited_once()
        emitter.failed.assert_not_awaited()

    async def test_run_agent_worker_rejects_missing_or_mismatched_model_receipt(self):
        cases = {
            "missing": [
                {"type": "text", "text": "Claimed completion without attribution."},
                {"type": "done"},
            ],
            "mismatched": [
                _model_runtime_event(model="wrong-model"),
                {"type": "text", "text": "Claimed completion with the wrong model."},
                {"type": "done"},
            ],
        }

        for label, scripted_events in cases.items():
            with self.subTest(label=label):
                emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
                fail_summary = ""
                fail_called = False

                async def _events():  # noqa: ANN202
                    for event in scripted_events:
                        yield event

                def _fail_execution(*_args, **kwargs):  # noqa: ANN202
                    nonlocal fail_called, fail_summary
                    fail_called = True
                    fail_summary = str(kwargs.get("summary") or "")

                def _get_execution(*_args, **_kwargs):  # noqa: ANN202
                    return {
                        "execution_id": "exec-runtime-proof",
                        "conversation_id": "sess-runtime-proof",
                        "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                        "state": "failed" if fail_called else "executing",
                        "summary": "Verify runtime proof.",
                        "bot_id": "nova",
                    }

                with (
                    patch(
                        "thomas.server.chat_delegation.run_agent_worker_events",
                        new=lambda *_args, **_kwargs: _events(),
                    ),
                    patch("thomas.server.chat_delegation.task_bot_runtime.update_execution"),
                    patch(
                        "thomas.server.chat_delegation.task_bot_runtime.fail_execution",
                        side_effect=_fail_execution,
                    ),
                    patch("thomas.server.chat_delegation.task_bot_runtime.complete_execution") as complete_execution,
                    patch(
                        "thomas.server.chat_delegation.task_bot_runtime.get_execution",
                        side_effect=_get_execution,
                    ),
                ):
                    await chat_delegation._run_agent_worker(
                        {},
                        execution_id="exec-runtime-proof",
                        prompt="Answer with verified model attribution.",
                        specialist_id="reasoning",
                        bot=_BotStub(),
                        emitter=emitter,
                        instructions="Answer accurately.",
                        repo_root=self.repo_root,
                        profile="test",
                        model_id="expected-model",
                        autonomy_level=1,
                    )

                self.assertRegex(fail_summary, r"model runtime receipt missing|invalid model runtime receipt")
                complete_execution.assert_not_called()
                emitter.completed.assert_not_awaited()
                emitter.failed.assert_awaited_once()
