import asyncio
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from thomas.server import chat_delegation, chat_delegation_runner


class _BotStub:
    def __init__(self, bot_id: str = "nova", name: str = "Nova") -> None:
        self.id = bot_id
        self.name = name

    def to_event_dict(self) -> dict[str, str]:
        return {"bot_id": self.id, "bot_name": self.name}


def _model_runtime_event(*, model: str = "test-model") -> dict[str, object]:
    return {
        "type": "model_runtime",
        "runtime": {
            "requested": {"profile": "test", "model": model, "api_key": "sk-never-persist"},
            "active": {
                "profile": "test",
                "provider": "test-provider",
                "model": model,
                "base_url": "https://user:pass@example.test/private?token=secret",
            },
            "failover_enabled": False,
            "failover_used": False,
            "attempts": [
                {
                    "profile": "test",
                    "provider": "test-provider",
                    "model": model,
                    "status": "success",
                    "error": "raw provider error must not persist",
                }
            ],
        },
    }


class TestChatDelegation(unittest.IsolatedAsyncioTestCase):
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
                repo_root=None,
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
                repo_root=None,
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
                repo_root=None,
                file_access=0,
            )

        self.assertEqual(record["state"], "executing")
        fail_execution.assert_not_called()
        self.assertEqual(update_execution.call_count, 4)
        ensure_workspace.assert_called_once_with("exec-read-only-artifact")
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
                repo_root=None,
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
                repo_root=None,
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
                    workspace="project",
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
                repo_root=Path(".").resolve(),
                worker_kwargs={"effort": "max"},
            )

        # A stop is recorded as cancelled, NOT as a failure: filing it with
        # fail_execution made every deliberate Stop look like a crash in the
        # task list, with a failed proof beside it.
        cancel_execution.assert_called_once()
        emitter.failed.assert_awaited_once()
        self.assertEqual(emitter.failed.await_args.kwargs["text"], "Stopped by you.")

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
                repo_root=Path(".").resolve(),
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
                        repo_root=Path(".").resolve(),
                        profile="test",
                        model_id="expected-model",
                        autonomy_level=1,
                    )

                self.assertRegex(fail_summary, r"model runtime receipt missing|invalid model runtime receipt")
                complete_execution.assert_not_called()
                emitter.completed.assert_not_awaited()
                emitter.failed.assert_awaited_once()

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
