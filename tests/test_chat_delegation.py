"""Chat delegation: dispatch, canvas routing, and how a task record is shaped.

The agent worker run cases live in the ``test_chat_delegation_worker_*``
modules; they were split out on 2026-09-20 when this file passed the 1200-line
hard limit.
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


class TestChatDelegation(unittest.IsolatedAsyncioTestCase):
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

    def test_supervisor_reserves_a_longer_idle_window_for_max_model_passes(self):
        self.assertEqual(
            chat_delegation_runner._supervisor_worker_timeout_s({"effort": "diligent"}, has_progress=True),
            chat_delegation_runner._WORKER_IDLE_EVENT_TIMEOUT_S,
        )
        self.assertGreaterEqual(
            chat_delegation_runner._supervisor_worker_timeout_s({"effort": "max"}, has_progress=True),
            360.0,
        )
        self.assertEqual(
            chat_delegation_runner._supervisor_worker_timeout_s({"effort": "max"}, has_progress=False),
            chat_delegation_runner._WORKER_FIRST_EVENT_TIMEOUT_S,
        )

    async def test_structured_dispatch_runs_even_when_prompt_is_conversational(self):
        emit_event = AsyncMock()
        expected = {"execution_id": "exec-chat"}
        with (
            patch("thomas.server.chat_delegation.pick_bot_for_specialist", return_value=_BotStub()),
            patch(
                "thomas.server.chat_delegation._start_agent_worker_delegation",
                new=AsyncMock(return_value=expected),
            ) as start_worker,
        ):
            result = await chat_delegation.start_background_delegation(
                {},
                session_id="sess-chat",
                prompt="let's think through this and plan how it should work",
                mode="max",
                recent_messages=[],
                emit_event=emit_event,
            )

        self.assertEqual(result, expected)
        start_worker.assert_awaited_once()
        emit_event.assert_not_awaited()

    async def test_auto_reply_first_force_can_dispatch(self):
        emit_event = AsyncMock()
        expected = {
            "execution_id": "exec-auto",
            "task_id": "task-auto",
            "session_id": "sess-auto",
            "backend_type": "task_manager",
            "state": "queued",
            "summary": "reply fast now and implement this plan in the background",
            "last_progress": "Queued for background execution.",
        }
        with (
            patch("thomas.server.chat_delegation.pick_bot_for_specialist") as pick_bot,
            patch(
                "thomas.server.chat_delegation._start_agent_worker_delegation", new=AsyncMock(return_value=expected)
            ) as start_worker,
        ):
            pick_bot.return_value = type(
                "BotStub",
                (),
                {
                    "id": "nova",
                    "name": "Nova",
                    "to_event_dict": lambda self: {"bot_id": "nova", "bot_name": "Nova"},
                },
            )()
            result = await chat_delegation.start_background_delegation(
                {},
                session_id="sess-auto",
                prompt="reply fast now and implement this plan in the background",
                mode="auto",
                recent_messages=[],
                emit_event=emit_event,
                force=True,
            )

        self.assertEqual(result, expected)
        start_worker.assert_awaited_once()
        emit_event.assert_not_awaited()

    async def test_agent_worker_failure_falls_back_to_task_manager(self):
        # The worker is now always attempted (no bridge gating); if it raises,
        # delegation falls back to the task manager.
        emit_event = AsyncMock()
        expected = {
            "execution_id": "exec-fallback",
            "task_id": "task-fallback",
            "session_id": "sess-max",
            "backend_type": "task_manager",
            "state": "queued",
            "summary": "please implement this plan",
            "last_progress": "Queued for background execution.",
            "bot_id": "nova",
            "bot_name": "Nova",
        }
        with (
            patch("thomas.server.chat_delegation.pick_bot_for_specialist") as pick_bot,
            patch(
                "thomas.server.chat_delegation._start_agent_worker_delegation",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch(
                "thomas.server.chat_delegation._start_task_manager_delegation", new=AsyncMock(return_value=expected)
            ) as fallback,
        ):
            pick_bot.return_value = type(
                "BotStub",
                (),
                {
                    "id": "nova",
                    "name": "Nova",
                    "to_event_dict": lambda self: {"bot_id": "nova", "bot_name": "Nova"},
                },
            )()
            result = await chat_delegation.start_background_delegation(
                {},
                session_id="sess-max",
                prompt="please implement this plan",
                mode="max",
                recent_messages=[],
                emit_event=emit_event,
                model_id="gpt-5.6-terra",
                reasoning_effort="high",
                specialist_id="coding",
            )

        self.assertEqual(result, expected)
        fallback.assert_awaited_once()
        self.assertIn("switched the task to Task Manager", fallback.await_args.kwargs["fallback_reason"])
        emit_event.assert_not_awaited()

    async def test_prompt_wording_does_not_create_implicit_fanout(self):
        emit_event = AsyncMock()
        record = {
            "execution_id": "exec-1",
            "task_id": "task-1",
            "session_id": "sess-multi",
            "backend_type": "task_manager",
            "state": "queued",
            "summary": "Spawn exactly three real sub-agents now and keep the response short.",
            "last_progress": "Queued for background execution.",
            "bot_id": "nova",
            "bot_name": "Nova",
        }
        with (
            patch(
                "thomas.server.chat_delegation.pick_bot_for_specialist",
                return_value=_BotStub(),
            ) as pick_bot,
            patch(
                "thomas.server.chat_delegation._start_agent_worker_delegation",
                new=AsyncMock(return_value=record),
            ) as start_task,
        ):
            result = await chat_delegation.start_background_delegation(
                {},
                session_id="sess-multi",
                prompt="Spawn exactly three real sub-agents now and keep the response short.",
                mode="auto",
                recent_messages=[],
                emit_event=emit_event,
                force=True,
            )

        self.assertEqual(result, record)
        start_task.assert_awaited_once()
        pick_bot.assert_called_once_with("reasoning")
        self.assertEqual(
            start_task.await_args.kwargs["prompt"],
            "Spawn exactly three real sub-agents now and keep the response short.",
        )
        emit_event.assert_not_awaited()

    def test_normalize_record_populates_bot_name(self):
        record = chat_delegation._normalize_record(
            {
                "execution_id": "exec-1",
                "task_id": "task-1",
                "conversation_id": "sess-1",
                "backend_type": "task_manager",
                "state": "queued",
                "summary": "Implement this plan",
                "progress_summary": "Queued for background execution.",
                "bot_id": "nova",
            }
        )
        self.assertEqual(record["bot_name"], "Nova")

    def test_normalize_record_exposes_every_verified_artifact(self):
        record = chat_delegation._normalize_record(
            {
                "execution_id": "exec-many",
                "conversation_id": "sess-1",
                "state": "completed",
                "proof_status": "verified",
                "proof": {
                    "status": "verified",
                    "artifacts": [
                        {"kind": "web", "path": "game/index.html"},
                        {"kind": "pdf", "path": "chart.pdf"},
                        {"kind": "text", "path": "recipe.md"},
                    ],
                },
            }
        )
        self.assertEqual([row["name"] for row in record["artifacts"]], ["index.html", "chart.pdf", "recipe.md"])
        self.assertEqual(len({row["id"] for row in record["artifacts"]}), 3)
        self.assertTrue(record["artifacts"][0]["url"].endswith("/game/index.html"))

    def test_normalize_record_hides_workspace_files_until_terminal_proof(self):
        with patch(
            "thomas.server.routes.deliverable_aiohttp.deliverable_entry",
            return_value="draft.html",
        ):
            record = chat_delegation._normalize_record(
                {
                    "execution_id": "exec-running",
                    "state": "executing",
                    "proof_status": "missing",
                    "proof": {},
                }
            )
        self.assertEqual(record["artifacts"], [])
        self.assertEqual(record["artifact_url"], "")

    async def test_delegation_emitter_reports_full_lifecycle(self):
        emit_event = AsyncMock()
        emitter = chat_delegation._DelegationEmitter(emit_event)
        bot = _BotStub()
        record = {
            "execution_id": "exec-1",
            "task_id": "task-1",
            "session_id": "sess-1",
            "backend_type": chat_delegation.TASK_MANAGER_BACKEND,
            "state": "queued",
            "summary": "Implement this plan",
            "last_progress": "Queued for background execution.",
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": [{"kind": "text", "path": "one.md"}]},
            "artifacts": [{"id": "exec-1:one.md", "name": "one.md", "url": "/deliverable/exec-1/one.md"}],
            "receipt": {"ok": True},
        }

        await emitter.started(record, specialist_id="coding", bot=bot)
        await emitter.progress(record, specialist_id="coding", bot=bot, text="Using grep.")
        await emitter.completed(record, specialist_id="coding", bot=bot, text="Done.")
        # One ending per execution reaches the chat, so the failure is another task's.
        await emitter.failed({**record, "execution_id": "exec-2"}, specialist_id="coding", bot=bot, text="Boom.")

        payloads = [call.args[0] for call in emit_event.await_args_list]
        self.assertEqual(
            [payload["type"] for payload in payloads],
            [
                "delegation_started",
                "delegation_progress",
                "delegation_completed",
                "delegation_failed",
            ],
        )
        self.assertEqual(payloads[0]["bot_name"], "Nova")
        self.assertEqual(payloads[1]["last_progress"], "Using grep.")
        self.assertEqual(payloads[2]["state"], "completed")
        self.assertEqual(payloads[2]["artifacts"][0]["name"], "one.md")
        self.assertTrue(payloads[2]["receipt"]["ok"])
        self.assertEqual(payloads[3]["state"], "failed")

    def test_helper_utilities_cover_repo_root_and_summary(self):
        self.assertEqual(chat_delegation._resolve_repo_root("."), Path(".").resolve())
        # Task cards are titled with a real name now, not a raw prompt truncation.
        self.assertEqual(
            chat_delegation.derive_task_title("hey thomas can you please build me a pac-man game"),
            "Build a pac-man game",
        )

    def test_session_active_delegations_filters_normalizes_and_builds_digest(self):
        rows = [
            {"execution_id": "exec-old", "conversation_id": "sess-1", "updated_at": "2026-03-28T00:00:00Z"},
            {"execution_id": "exec-skip", "conversation_id": "sess-2", "updated_at": "2026-03-29T00:00:00Z"},
            {"execution_id": "exec-new", "conversation_id": "sess-1", "updated_at": "2026-03-29T00:00:00Z"},
        ]

        def _get_execution(execution_id: str, root: Path):  # noqa: ANN001
            _ = root
            if execution_id == "exec-old":
                return {
                    "execution_id": execution_id,
                    "conversation_id": "sess-1",
                    "backend_type": chat_delegation.TASK_MANAGER_BACKEND,
                    "state": "queued",
                    "progress_summary": "Queued for background execution.",
                    "bot_id": "nova",
                    "updated_at": "2026-03-28T00:00:00Z",
                }
            return None

        with (
            patch("thomas.server.chat_delegation.task_bot_runtime.list_user_executions", return_value=rows),
            patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", side_effect=_get_execution),
        ):
            delegations = chat_delegation.session_active_delegations("sess-1")
            digest = chat_delegation.build_active_task_digest("sess-1", limit=1)

        self.assertEqual([row["execution_id"] for row in delegations], ["exec-new", "exec-old"])
        self.assertIn("Background work in this chat:", digest)
        self.assertIn("worker [requested via task manager]", digest)

    def test_live_repo_change_detection_uses_content_and_ignores_library(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            target = root / "tests" / "probe_test.py"
            target.parent.mkdir(parents=True)
            target.write_text("value = 1\n", encoding="utf-8")
            library_note = root / "library" / "entries" / "note.md"
            library_note.parent.mkdir(parents=True)
            library_note.write_text("note v1\n", encoding="utf-8")

            baseline = chat_delegation._live_repo_workspace_mtimes(root)

            target.write_text("value = 1\n", encoding="utf-8")
            library_note.write_text("note v2\n", encoding="utf-8")
            self.assertNotIn("tests/probe_test.py", chat_delegation._live_repo_files_changed_since(root, baseline))
            self.assertNotIn("library/entries/note.md", chat_delegation._live_repo_files_changed_since(root, baseline))

            target.write_text("value = 2\n", encoding="utf-8")
            self.assertEqual(chat_delegation._live_repo_files_changed_since(root, baseline), ["tests/probe_test.py"])

    def test_agent_worker_runtime_profile_exposes_ui_build_quality_label(self):
        profile = chat_delegation._agent_worker_runtime_profile(
            autonomy_level=4,
            file_access=2,
            effort="optimal",
            guardrails="guarded",
            requires_live_repo_change=True,
        )

        self.assertEqual(profile["effort"], "optimal")
        self.assertEqual(profile["build_quality_label"], "Standard")
        self.assertEqual(profile["file_access_label"], "project")

    def test_live_repo_replan_after_no_counted_write_requires_changed_content(self):
        prompt = chat_delegation._replan_prompt(
            "Modify Thomas.",
            "self-development task changed no live repo files; write tools used did not change counted files: "
            "fs.write_file",
            2,
            3,
        )

        self.assertIn("write did not change any counted live-repo source/test/doc content", prompt)
        self.assertIn("must change file content, not rewrite identical bytes", prompt)
        self.assertIn("outside runtime/, output/, library/", prompt)
        self.assertIn("LIVE REPO COMPLETION REQUIREMENT:", prompt)

    async def test_start_background_delegation_uses_agent_worker(self):
        # With the bridge gating removed, the agent worker is the unconditional
        # primary delegation path.
        emit_event = AsyncMock()
        expected = {
            "execution_id": "exec-native",
            "task_id": "task-native",
            "session_id": "sess-native",
            "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
            "state": "executing",
            "summary": "please implement this plan",
            "last_progress": "Provider-native worker is running.",
        }
        with (
            patch("thomas.server.chat_delegation.pick_bot_for_specialist", return_value=_BotStub()) as pick_bot,
            patch(
                "thomas.server.chat_delegation._start_agent_worker_delegation",
                new=AsyncMock(return_value=expected),
            ) as start_worker,
        ):
            result = await chat_delegation.start_background_delegation(
                {},
                session_id="sess-native",
                prompt="please implement this plan",
                mode="max",
                recent_messages=[],
                emit_event=emit_event,
                model_id="gpt-5.6-terra",
                reasoning_effort="high",
                specialist_id="coding",
            )

        self.assertEqual(result, expected)
        pick_bot.assert_called_once_with("coding")
        start_worker.assert_awaited_once()
        self.assertEqual(start_worker.await_args.kwargs["model_id"], "gpt-5.6-terra")
        self.assertEqual(start_worker.await_args.kwargs["reasoning_effort"], "high")

    async def test_start_task_manager_delegation_reports_failure(self):
        failed_result = SimpleNamespace(ok=False, execution_id="exec-fail", task_id="task-fail", error="boom")
        emitter = SimpleNamespace(failed=AsyncMock())
        with patch("thomas.server.chat_delegation.dispatch_async", new=AsyncMock(return_value=failed_result)):
            record = await chat_delegation._start_task_manager_delegation(
                session_id="sess-fail",
                prompt="please implement this plan",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=self.repo_root,
            )

        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["last_progress"], "boom")
        emitter.failed.assert_awaited_once()

    async def test_start_task_manager_delegation_reports_started_record(self):
        success_result = SimpleNamespace(ok=True, execution_id="exec-ok", task_id="task-ok", error="")
        emitter = SimpleNamespace(started=AsyncMock())
        payload = {
            "execution_id": "exec-ok",
            "task_id": "task-ok",
            "conversation_id": "sess-ok",
            "backend_type": chat_delegation.TASK_MANAGER_BACKEND,
            "state": "queued",
            "summary": "please implement this plan",
            "progress_summary": "Queued for background execution.",
            "bot_id": "nova",
            "updated_at": "2026-03-29T00:00:00Z",
        }
        fallback_reason = "Provider worker failed, so Thomas switched the task to Task Manager."

        def _update_execution(_execution_id, **kwargs):  # noqa: ANN001
            payload["runtime_profile"] = kwargs["runtime_profile"]
            payload["progress_summary"] = kwargs["progress_summary"]

        with (
            patch("thomas.server.chat_delegation.dispatch_async", new=AsyncMock(return_value=success_result)),
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.update_execution", side_effect=_update_execution
            ) as update_execution,
            patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", return_value=payload),
        ):
            record = await chat_delegation._start_task_manager_delegation(
                session_id="sess-ok",
                prompt="please implement this plan",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=self.repo_root,
                fallback_reason=fallback_reason,
            )

        self.assertEqual(record["execution_id"], "exec-ok")
        self.assertEqual(record["last_progress"], fallback_reason)
        self.assertEqual(record["runtime_profile"]["fallback_from"], "provider_native_worker")
        update_execution.assert_called_once()
        emitter.started.assert_awaited_once()

    async def test_workspace_artifact_delegation_creates_execution_and_worker_task(self):
        emitter = SimpleNamespace(started=AsyncMock(), failed=AsyncMock())
        created_coroutines = []

        def _create_task(coro):  # noqa: ANN001
            created_coroutines.append(coro)
            coro.close()
            return SimpleNamespace()

        with (
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.create_execution",
                return_value={"execution_id": "exec-native"},
            ) as create_execution,
            patch("thomas.server.chat_delegation.task_bot_runtime.update_execution") as update_execution,
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.get_execution",
                return_value={
                    "execution_id": "exec-native",
                    "task_id": "",
                    "conversation_id": "sess-native",
                    "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                    "state": "executing",
                    "summary": "Make a web app.",
                    "progress_summary": "Provider-native worker is running.",
                    "bot_id": "nova",
                },
            ),
            patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution") as fail_execution,
            patch("thomas.server.chat_delegation.asyncio.create_task", side_effect=_create_task),
        ):
            record = await chat_delegation._start_agent_worker_delegation(
                {},
                session_id="sess-native",
                prompt="Okay, make me a web app.",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=self.repo_root,
                file_access=1,
                model_id="gpt-5.6-luna",
                reasoning_effort="xhigh",
                memory_enabled=False,
            )

        self.assertEqual(record["backend_type"], chat_delegation.PROVIDER_NATIVE_BACKEND)
        self.assertEqual(update_execution.call_count, 4)
        self.assertEqual(len(created_coroutines), 1)
        runtime_profile = create_execution.call_args.kwargs["runtime_profile"]
        self.assertEqual(runtime_profile["autonomy_level"], 4)
        self.assertEqual(runtime_profile["file_access"], 1)
        self.assertEqual(runtime_profile["effort"], "diligent")
        self.assertEqual(runtime_profile["model_id"], "gpt-5.6-luna")
        self.assertEqual(runtime_profile["reasoning_effort"], "xhigh")
        self.assertEqual(runtime_profile["build_quality_label"], "diligent")
        self.assertIs(runtime_profile["requires_live_repo_change"], False)
        self.assertEqual(runtime_profile["max_attempts"], 3)
        self.assertEqual(runtime_profile["group_expected_count"], 1)
        self.assertFalse(runtime_profile["memory_enabled"])
        emitter.started.assert_awaited_once()
        emitter.failed.assert_not_awaited()
        fail_execution.assert_not_called()

    async def test_artifact_wording_does_not_trigger_file_access_rejection(self):
        emitter = SimpleNamespace(started=AsyncMock(), failed=AsyncMock())
        payload = {
            "execution_id": "exec-read-only-artifact",
            "conversation_id": "sess-read-only-artifact",
            "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
            "state": "executing",
            "summary": "Make a web app.",
            "progress_summary": "Provider-native worker is running.",
            "bot_id": "nova",
        }

        def _supervisor(*_args, **_kwargs):  # noqa: ANN202
            async def _noop():
                return None

            return _noop()

        def _create_task(coro):  # noqa: ANN001, ANN202
            coro.close()
            return SimpleNamespace()

        with (
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.create_execution",
                return_value={"execution_id": "exec-read-only-artifact"},
            ),
            patch("thomas.server.chat_delegation.task_bot_runtime.update_execution") as update_execution,
            patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution") as fail_execution,
            patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", return_value=payload),
            patch(
                "thomas.server.chat_delegation._ensure_task_workspace",
                return_value=Path("workspace").resolve(),
            ) as ensure_workspace,
            patch(
                "thomas.server.chat_delegation._run_agent_worker_supervised", side_effect=_supervisor
            ) as run_supervisor,
            patch("thomas.server.chat_delegation.asyncio.create_task", side_effect=_create_task) as create_task,
        ):
            record = await chat_delegation._start_agent_worker_delegation(
                {},
                session_id="sess-read-only-artifact",
                prompt="Code a small web app.",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=self.repo_root,
                file_access=0,
            )

        self.assertEqual(record["state"], "executing")
        fail_execution.assert_not_called()
        self.assertEqual(update_execution.call_count, 4)
        # A coding task now runs inside its own Build project rather than the
        # plain per-task workspace, so that Build has a session to show: run in
        # a bare workspace, which Build never walks, the pane stayed empty for
        # the whole life of the run.
        ensure_workspace.assert_not_called()
        run_supervisor.assert_called_once()
        create_task.assert_called_once()
        emitter.started.assert_awaited_once()
        emitter.failed.assert_not_awaited()

    async def test_self_development_prompt_requires_project_file_access(self):
        emitter = SimpleNamespace(started=AsyncMock(), failed=AsyncMock())
        payload = {
            "execution_id": "exec-native",
            "conversation_id": "sess-native",
            "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
            "state": "failed",
            "summary": "Modify Thomas.",
            "progress_summary": "Raise the file-access dial to Project or higher.",
            "bot_id": "nova",
        }
        with (
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.create_execution",
                return_value={"execution_id": "exec-native"},
            ),
            patch("thomas.server.chat_delegation.task_bot_runtime.update_execution"),
            patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution") as fail_execution,
            patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", return_value=payload),
            patch("thomas.server.chat_delegation.asyncio.create_task") as create_task,
        ):
            record = await chat_delegation._start_agent_worker_delegation(
                {},
                session_id="sess-native",
                prompt="Modify Thomas's code in the live repo.",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=self.repo_root,
                file_access=1,
                workspace="project",
            )

        self.assertEqual(record["state"], "failed")
        fail_execution.assert_called_once()
        create_task.assert_not_called()
        emitter.failed.assert_awaited_once()

    async def test_answer_only_worker_is_told_not_to_create_or_inspect_files(self):
        emitter = SimpleNamespace(started=AsyncMock(), failed=AsyncMock())
        captured = {}

        def _supervisor(*_args, **kwargs):  # noqa: ANN003
            captured.update(kwargs["worker_kwargs"])

            async def _noop():
                return None

            return _noop()

        def _create_task(coro):  # noqa: ANN001
            coro.close()
            return SimpleNamespace()

        with (
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.create_execution",
                return_value={"execution_id": "exec-answer"},
            ),
            patch("thomas.server.chat_delegation.task_bot_runtime.update_execution"),
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.get_execution",
                return_value={
                    "execution_id": "exec-answer",
                    "conversation_id": "sess-answer",
                    "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                    "state": "executing",
                    "summary": "Write recommendations in chat.",
                    "progress_summary": "Provider-native worker is running.",
                    "bot_id": "nova",
                },
            ),
            patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution") as fail_execution,
            patch("thomas.server.chat_delegation._run_agent_worker_supervised", new=_supervisor),
            patch("thomas.server.chat_delegation.asyncio.create_task", side_effect=_create_task),
        ):
            await chat_delegation._start_agent_worker_delegation(
                {},
                session_id="sess-answer",
                prompt="Write recommendations for a website.",
                specialist_id="reasoning",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=self.repo_root,
                file_access=0,
            )

        instructions = captured["instructions"]
        self.assertEqual(captured["file_access"], 0)
        self.assertIn("ONLY when the user explicitly requests an artifact", instructions)
        self.assertIn("do not inspect the empty workspace and do not create files", instructions)
        self.assertIn("return the requested answer itself, not a readiness notice", instructions)
        fail_execution.assert_not_called()
        emitter.started.assert_awaited_once()
        emitter.failed.assert_not_awaited()

    async def test_self_development_prompt_runs_worker_in_repo_at_project_access(self):
        emitter = SimpleNamespace(started=AsyncMock())
        captured = {}
        created_coroutines = []

        def _supervisor(*args, **kwargs):  # noqa: ANN001, ANN003
            captured.update(kwargs["worker_kwargs"])
            captured["runner"] = args[0]

            async def _noop():
                return None

            return _noop()

        def _create_task(coro):  # noqa: ANN001
            created_coroutines.append(coro)
            coro.close()
            return SimpleNamespace()

        import os
        import subprocess

        from thomas.server import green_checkout

        with tempfile.TemporaryDirectory() as d:
            root = (Path(d) / "blue").resolve()
            root.mkdir()
            (root / "README.md").write_text("blue\n", encoding="utf-8")
            git = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
            for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "init"]):
                subprocess.run([*git, *args], cwd=root, check=True, capture_output=True)
            with (
                patch.dict(os.environ, {green_checkout.GREEN_ROOT_ENV: str(Path(d) / "green")}),
                patch(
                    "thomas.server.chat_delegation.task_bot_runtime.create_execution",
                    return_value={"execution_id": "exec-native"},
                ) as create_execution,
                patch("thomas.server.chat_delegation.task_bot_runtime.update_execution"),
                patch(
                    "thomas.server.chat_delegation.task_bot_runtime.get_execution",
                    return_value={
                        "execution_id": "exec-native",
                        "conversation_id": "sess-native",
                        "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                        "state": "executing",
                        "summary": "Modify Thomas.",
                        "progress_summary": "Provider-native worker is running.",
                        "bot_id": "nova",
                    },
                ),
                patch("thomas.server.chat_delegation._run_agent_worker_supervised", new=_supervisor),
                patch("thomas.server.chat_delegation.asyncio.create_task", side_effect=_create_task),
            ):
                await chat_delegation._start_agent_worker_delegation(
                    {},
                    session_id="sess-native",
                    prompt="Work in the live Thomas repo and modify Thomas's code.",
                    specialist_id="coding",
                    bot=_BotStub(),
                    emitter=emitter,
                    repo_root=root,
                    file_access=2,
                    workspace="project",
                )

                green = green_checkout.find_green("exec-native")
                # The worker runs in green, a private clone; the live checkout is never its work folder.
                self.assertIsNotNone(green)
                self.assertEqual(captured["work_dir"], green.work)
                self.assertNotEqual(Path(captured["work_dir"]).resolve(), root)
                green_checkout.remove_green(green)
        self.assertIs(captured["requires_live_repo_change"], True)
        self.assertIn("private copy", captured["instructions"])
        runtime_profile = create_execution.call_args.kwargs["runtime_profile"]
        self.assertEqual(runtime_profile["autonomy_level"], 4)
        self.assertEqual(runtime_profile["file_access"], 2)
        self.assertEqual(runtime_profile["file_access_label"], "project")
        self.assertEqual(runtime_profile["build_quality_label"], "diligent")
        self.assertIs(runtime_profile["requires_live_repo_change"], True)
        self.assertEqual(runtime_profile["max_attempts"], 3)
        self.assertEqual(len(created_coroutines), 1)
