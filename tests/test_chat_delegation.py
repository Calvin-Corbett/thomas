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
                "thomas.server.chat_delegation._start_task_manager_delegation", new=AsyncMock(return_value=expected)
            ) as start_task,
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
        start_task.assert_awaited_once()
        emit_event.assert_not_awaited()

    async def test_provider_native_failure_falls_back_to_task_manager(self):
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
                "thomas.server.chat_delegation._start_provider_native_delegation",
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
            fake_app = type(
                "AppStub",
                (),
                {
                    "get": lambda self, key, default=None: (
                        {"bridge": type("BridgeStub", (), {"is_running": True})()}
                        if key == chat_delegation.APP_CODEX_BRIDGE
                        else default
                    ),
                },
            )()
            result = await chat_delegation.start_background_delegation(
                fake_app,
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

    def test_helper_utilities_cover_repo_root_bridge_summary_and_specialist(self):
        self.assertEqual(chat_delegation._resolve_repo_root("."), Path(".").resolve())
        self.assertEqual(
            chat_delegation._coerce_bridge({chat_delegation.APP_CODEX_BRIDGE: {"bridge": "ok"}}),
            "ok",
        )
        self.assertIsNone(chat_delegation._coerce_bridge(object()))
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

    async def test_start_background_delegation_uses_provider_native_when_bridge_running(self):
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
                "thomas.server.chat_delegation._start_provider_native_delegation",
                new=AsyncMock(return_value=expected),
            ) as start_native,
        ):
            app = {chat_delegation.APP_CODEX_BRIDGE: {"bridge": SimpleNamespace(is_running=True)}}
            result = await chat_delegation.start_background_delegation(
                app,
                session_id="sess-native",
                prompt="please implement this plan",
                mode="max",
                recent_messages=[],
                emit_event=emit_event,
            )

        self.assertEqual(result, expected)
        pick_bot.assert_called_once_with("coding")
        start_native.assert_awaited_once()

    async def test_start_background_delegation_lazily_starts_logged_in_bridge(self):
        emit_event = AsyncMock()
        expected = {
            "execution_id": "exec-native-lazy",
            "task_id": "task-native-lazy",
            "session_id": "sess-native-lazy",
            "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
            "state": "executing",
            "summary": "please set up Discord for Thomas",
            "last_progress": "Provider-native worker is running.",
        }
        bridge = SimpleNamespace(
            is_running=False,
            start=AsyncMock(),
            check_auth=AsyncMock(return_value=SimpleNamespace(logged_in=True)),
        )
        with (
            patch("thomas.codex.bridge.CodexBridge", return_value=bridge),
            patch("thomas.server.chat_delegation.pick_bot_for_specialist", return_value=_BotStub()) as pick_bot,
            patch(
                "thomas.server.chat_delegation._start_provider_native_delegation",
                new=AsyncMock(return_value=expected),
            ) as start_native,
        ):
            app = {chat_delegation.APP_CODEX_BRIDGE: {"bridge": None}}
            result = await chat_delegation.start_background_delegation(
                app,
                session_id="sess-native-lazy",
                prompt="please set up Discord for Thomas",
                mode="max",
                recent_messages=[],
                emit_event=emit_event,
            )

        self.assertEqual(result, expected)
        bridge.start.assert_awaited_once()
        bridge.check_auth.assert_awaited_once()
        pick_bot.assert_called_once_with("tools")
        start_native.assert_awaited_once()

    async def test_start_background_delegation_falls_back_when_lazy_bridge_is_logged_out(self):
        emit_event = AsyncMock()
        expected = {
            "execution_id": "exec-fallback-lazy",
            "task_id": "task-fallback-lazy",
            "session_id": "sess-fallback-lazy",
            "backend_type": chat_delegation.TASK_MANAGER_BACKEND,
            "state": "queued",
            "summary": "please set up Discord for Thomas",
            "last_progress": "Queued for background execution.",
        }
        bridge = SimpleNamespace(
            is_running=False,
            start=AsyncMock(),
            check_auth=AsyncMock(return_value=SimpleNamespace(logged_in=False)),
        )
        with (
            patch("thomas.codex.bridge.CodexBridge", return_value=bridge),
            patch("thomas.server.chat_delegation.pick_bot_for_specialist", return_value=_BotStub()) as pick_bot,
            patch(
                "thomas.server.chat_delegation._start_task_manager_delegation",
                new=AsyncMock(return_value=expected),
            ) as start_task,
        ):
            app = {chat_delegation.APP_CODEX_BRIDGE: {"bridge": None}}
            result = await chat_delegation.start_background_delegation(
                app,
                session_id="sess-fallback-lazy",
                prompt="please set up Discord for Thomas",
                mode="max",
                recent_messages=[],
                emit_event=emit_event,
            )

        self.assertEqual(result, expected)
        bridge.start.assert_awaited_once()
        bridge.check_auth.assert_awaited_once()
        pick_bot.assert_called_once_with("tools")
        start_task.assert_awaited_once()

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

    async def test_start_provider_native_delegation_creates_execution_and_worker_task(self):
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
            ),
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
            record = await chat_delegation._start_provider_native_delegation(
                SimpleNamespace(chat=AsyncMock()),
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
        emitter.started.assert_awaited_once()

    async def test_run_provider_native_worker_reports_progress_and_completion(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

        async def _events():  # noqa: ANN202
            yield {"type": "tool_start", "name": "grep"}
            yield {"type": "tool_output"}
            yield {"type": "done"}

        bridge = SimpleNamespace(chat=lambda *args, **kwargs: _events())  # noqa: ARG005
        with (
            patch("thomas.server.chat_delegation.task_bot_runtime.update_execution") as update_execution,
            patch("thomas.server.chat_delegation.task_bot_runtime.complete_execution") as complete_execution,
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.get_execution",
                return_value={
                    "execution_id": "exec-native",
                    "conversation_id": "sess-native",
                    "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                    "state": "executing",
                    "summary": "please implement this plan",
                    "progress_summary": "Completed a tool step.",
                    "bot_id": "nova",
                },
            ),
        ):
            await chat_delegation._run_provider_native_worker(
                bridge,
                execution_id="exec-native",
                prompt="please implement this plan",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                instructions="Do the work.",
                repo_root=Path(".").resolve(),
            )

        self.assertEqual(update_execution.call_count, 2)
        complete_execution.assert_called_once()
        self.assertEqual(emitter.progress.await_count, 2)
        emitter.completed.assert_awaited_once()
        emitter.failed.assert_not_awaited()

    async def test_run_provider_native_worker_reports_failure(self):
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

        async def _events():  # noqa: ANN202
            yield {"type": "error", "error": "bridge exploded"}

        bridge = SimpleNamespace(chat=lambda *args, **kwargs: _events())  # noqa: ARG005
        with (
            patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution") as fail_execution,
            patch(
                "thomas.server.chat_delegation.task_bot_runtime.get_execution",
                return_value={
                    "execution_id": "exec-native",
                    "conversation_id": "sess-native",
                    "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                    "state": "failed",
                    "summary": "please implement this plan",
                    "progress_summary": "Background execution failed: bridge exploded",
                    "bot_id": "nova",
                },
            ),
        ):
            await chat_delegation._run_provider_native_worker(
                bridge,
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


if __name__ == "__main__":
    unittest.main()
