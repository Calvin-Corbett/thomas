import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from thomas.server import chat_delegation


class _BotStub:
    def __init__(self, bot_id: str = "nova", name: str = "Nova") -> None:
        self.id = bot_id
        self.name = name

    def to_event_dict(self) -> dict[str, str]:
        return {"bot_id": self.id, "bot_name": self.name}


class TestChatDelegation(unittest.IsolatedAsyncioTestCase):
    async def test_max_mode_skips_exploratory_conversation(self):
        emit_event = AsyncMock()
        result = await chat_delegation.start_background_delegation(
            {},
            session_id="sess-chat",
            prompt="let's think through this and plan how it should work",
            mode="max",
            recent_messages=[],
            emit_event=emit_event,
        )
        self.assertIsNone(result)
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
            )

        self.assertEqual(result, expected)
        fallback.assert_awaited_once()
        emit_event.assert_not_awaited()

    async def test_forced_multi_agent_prompt_fans_out_multiple_distinct_bots(self):
        emit_event = AsyncMock()
        bot_stubs = [
            type(
                "BotStub",
                (),
                {
                    "id": "nova",
                    "name": "Nova",
                    "to_event_dict": lambda self: {"bot_id": "nova", "bot_name": "Nova"},
                },
            )(),
            type(
                "BotStub",
                (),
                {
                    "id": "zach",
                    "name": "Zach",
                    "to_event_dict": lambda self: {"bot_id": "zach", "bot_name": "Zach"},
                },
            )(),
            type(
                "BotStub",
                (),
                {
                    "id": "trey",
                    "name": "Trey",
                    "to_event_dict": lambda self: {"bot_id": "trey", "bot_name": "Trey"},
                },
            )(),
        ]
        records = [
            {
                "execution_id": "exec-1",
                "task_id": "task-1",
                "session_id": "sess-multi",
                "backend_type": "task_manager",
                "state": "queued",
                "summary": "helper one",
                "last_progress": "Queued for background execution.",
                "bot_id": "nova",
                "bot_name": "Nova",
            },
            {
                "execution_id": "exec-2",
                "task_id": "task-2",
                "session_id": "sess-multi",
                "backend_type": "task_manager",
                "state": "queued",
                "summary": "helper two",
                "last_progress": "Queued for background execution.",
                "bot_id": "zach",
                "bot_name": "Zach",
            },
            {
                "execution_id": "exec-3",
                "task_id": "task-3",
                "session_id": "sess-multi",
                "backend_type": "task_manager",
                "state": "queued",
                "summary": "helper three",
                "last_progress": "Queued for background execution.",
                "bot_id": "trey",
                "bot_name": "Trey",
            },
        ]
        with (
            patch(
                "thomas.server.chat_delegation.pick_bot_for_specialist",
                side_effect=bot_stubs,
            ) as pick_bot,
            patch(
                "thomas.server.chat_delegation._start_task_manager_delegation",
                new=AsyncMock(side_effect=records),
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

        self.assertEqual(result, records)
        self.assertEqual(start_task.await_count, 3)
        self.assertEqual(pick_bot.call_count, 3)
        exclude_sets = [set(call.kwargs.get("exclude") or set()) for call in pick_bot.call_args_list]
        self.assertEqual(exclude_sets[0], set())
        self.assertEqual(exclude_sets[1], {"nova"})
        self.assertEqual(exclude_sets[2], {"nova", "zach"})
        helper_prompts = [call.kwargs["prompt"] for call in start_task.await_args_list]
        self.assertTrue(all("[Helper assignment]" in prompt for prompt in helper_prompts))
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

    def test_requested_delegate_count_parses_multi_agent_prompt(self):
        self.assertEqual(
            chat_delegation._requested_delegate_count("Spawn exactly three real sub-agents now."),
            3,
        )
        self.assertEqual(chat_delegation._requested_delegate_count("launch a couple helpers"), 2)
        self.assertEqual(chat_delegation._requested_delegate_count("just do the task"), 1)

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
        }

        await emitter.started(record, specialist_id="coding", bot=bot)
        await emitter.progress(record, specialist_id="coding", bot=bot, text="Using grep.")
        await emitter.completed(record, specialist_id="coding", bot=bot, text="Done.")
        await emitter.failed(record, specialist_id="coding", bot=bot, text="Boom.")

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
        self.assertEqual(payloads[3]["state"], "failed")

    def test_helper_utilities_cover_repo_root_summary_and_specialist(self):
        self.assertEqual(chat_delegation._resolve_repo_root("."), Path(".").resolve())
        # Task cards are titled with a real name now, not a raw prompt truncation.
        self.assertEqual(
            chat_delegation.derive_task_title("hey thomas can you please build me a pac-man game"),
            "Build a pac-man game",
        )
        self.assertEqual(chat_delegation._infer_specialist("Please investigate and compare this."), "research")
        self.assertEqual(chat_delegation._infer_specialist("Run this command and configure it."), "tools")
        self.assertEqual(chat_delegation._infer_specialist("Just think it through."), "reasoning")
        self.assertEqual(
            chat_delegation._helper_prompt("Do the task", helper_index=1, helper_count=1, bot_name="Nova"),
            "Do the task",
        )
        self.assertIn(
            "[Helper assignment]",
            chat_delegation._helper_prompt("Do the task", helper_index=2, helper_count=3, bot_name="Zach"),
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
            patch("thomas.server.chat_delegation.task_bot_runtime.list_executions", return_value=rows),
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
            )

        self.assertEqual(result, expected)
        pick_bot.assert_called_once_with("coding")
        start_worker.assert_awaited_once()

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
                repo_root=None,
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
        with (
            patch("thomas.server.chat_delegation.dispatch_async", new=AsyncMock(return_value=success_result)),
            patch("thomas.server.chat_delegation.task_bot_runtime.update_execution") as update_execution,
            patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", return_value=payload),
        ):
            record = await chat_delegation._start_task_manager_delegation(
                session_id="sess-ok",
                prompt="please implement this plan",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=None,
            )

        self.assertEqual(record["execution_id"], "exec-ok")
        update_execution.assert_called_once()
        emitter.started.assert_awaited_once()

    async def test_start_agent_worker_delegation_creates_execution_and_worker_task(self):
        emitter = SimpleNamespace(started=AsyncMock())
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
                    "summary": "please implement this plan",
                    "progress_summary": "Provider-native worker is running.",
                    "bot_id": "nova",
                },
            ),
            patch("thomas.server.chat_delegation.asyncio.create_task", side_effect=_create_task),
        ):
            record = await chat_delegation._start_agent_worker_delegation(
                {},
                session_id="sess-native",
                prompt="please implement this plan",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=None,
            )

        self.assertEqual(record["backend_type"], chat_delegation.PROVIDER_NATIVE_BACKEND)
        self.assertEqual(update_execution.call_count, 4)
        self.assertEqual(len(created_coroutines), 1)
        runtime_profile = create_execution.call_args.kwargs["runtime_profile"]
        self.assertEqual(runtime_profile["autonomy_level"], 4)
        self.assertEqual(runtime_profile["file_access"], 1)
        self.assertEqual(runtime_profile["effort"], "diligent")
        self.assertEqual(runtime_profile["build_quality_label"], "diligent")
        self.assertIs(runtime_profile["requires_live_repo_change"], False)
        self.assertEqual(runtime_profile["max_attempts"], 3)
        emitter.started.assert_awaited_once()

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
                repo_root=None,
                file_access=1,
            )

        self.assertEqual(record["state"], "failed")
        fail_execution.assert_called_once()
        create_task.assert_not_called()
        emitter.failed.assert_awaited_once()

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

        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            with (
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
                )

        self.assertEqual(captured["work_dir"], root)
        self.assertIs(captured["requires_live_repo_change"], True)
        self.assertIn("live Thomas repo", captured["instructions"])
        runtime_profile = create_execution.call_args.kwargs["runtime_profile"]
        self.assertEqual(runtime_profile["autonomy_level"], 4)
        self.assertEqual(runtime_profile["file_access"], 2)
        self.assertEqual(runtime_profile["file_access_label"], "project")
        self.assertEqual(runtime_profile["build_quality_label"], "diligent")
        self.assertIs(runtime_profile["requires_live_repo_change"], True)
        self.assertEqual(runtime_profile["max_attempts"], 3)
        self.assertEqual(len(created_coroutines), 1)

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
                repo_root=Path(".").resolve(),
                worker_kwargs={},
            )

        fail_execution.assert_called_once()
        self.assertEqual(fail_execution.call_args.kwargs["blocker"], "provider_native_timeout")
        emitter.failed.assert_awaited_once()

    async def test_run_agent_worker_reports_progress_and_completion(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

        async def _events():  # noqa: ANN202
            yield {"type": "progress", "text": "Provider-native worker is initializing."}
            yield {"type": "tool_start", "name": "grep"}
            yield {"type": "tool_output"}
            yield {"type": "done"}

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
                new=lambda *args, **kwargs: _events(),  # noqa: ARG005
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
                repo_root=Path(".").resolve(),
            )

        self.assertEqual(update_execution.call_count, 4)
        complete_execution.assert_called_once()
        self.assertEqual(emitter.progress.await_count, 4)
        self.assertEqual(emitter.progress.await_args_list[0].kwargs["text"], "Preparing workspace change baseline.")
        self.assertEqual(emitter.progress.await_args_list[1].kwargs["text"], "Provider-native worker is initializing.")
        emitter.completed.assert_awaited_once()
        emitter.failed.assert_not_awaited()

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
                "Preparing live repo change baseline.",
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
        self.assertIn("next substantive tool call must be fs.write_file", prompts[1])
        self.assertIn("prefer a small regression test or catalog policy edit", prompts[1])
        self.assertIn("Stop broad inspection now", prompts[2])
        self.assertIn("next substantive tool call must be fs.write_file", prompts[2])
        self.assertIn("fs.write_file", prompts[1])
        self.assertIn("no write tool was used", fail_execution.call_args.kwargs["summary"])
        emitter.failed.assert_awaited_once()
        emitter.completed.assert_not_awaited()

    async def test_run_agent_worker_live_repo_ignores_generated_test_result_log(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            result_log = root / "thomas_test_results.jsonl"
            fail_called = False

            async def _events():  # noqa: ANN202
                result_log.write_text('{"ok": true}\n', encoding="utf-8")
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

    async def test_run_agent_worker_live_repo_rejects_docs_only_for_code_task(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            target = root / "docs" / "self_development" / "note.md"
            fail_called = False

            async def _events():  # noqa: ANN202
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("documented instead of fixed", encoding="utf-8")
                yield {"type": "tool_start", "name": "fs.write_file"}
                yield {"type": "tool_output", "name": "fs.write_file", "ok": True}
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

        fail_execution.assert_called_once()
        self.assertIn("only documentation files", fail_execution.call_args.kwargs["summary"])
        emitter.failed.assert_awaited_once()
        emitter.completed.assert_not_awaited()

    async def test_run_agent_worker_reports_failure(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        fail_called = False

        async def _events():  # noqa: ANN202
            yield {"type": "error", "error": "worker exploded"}

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
                repo_root=Path(".").resolve(),
            )

        fail_execution.assert_called_once()
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
                repo_root=Path(".").resolve(),
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
                    repo_root=Path(".").resolve(),
                )

        fail_execution.assert_called_once()
        self.assertEqual(fail_execution.call_args.kwargs.get("blocker"), "cancelled")
        emitter.failed.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
