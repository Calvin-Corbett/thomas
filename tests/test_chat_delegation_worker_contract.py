"""Focused contract coverage for delegated browser/artifact workers."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from thomas.server import chat_delegation


class _BotStub:
    id = "nova"
    name = "Nova"

    def to_event_dict(self) -> dict[str, str]:
        return {"bot_id": self.id, "bot_name": self.name}


@pytest.mark.asyncio
async def test_worker_instructions_expose_browser_and_artifact_contract() -> None:
    emitter = SimpleNamespace(started=AsyncMock())
    captured: dict = {}
    created_coroutines = []

    def _supervisor(*args, **kwargs):  # noqa: ANN001, ANN003
        captured.update(kwargs["worker_kwargs"])

        async def _noop() -> None:
            return None

        return _noop()

    def _create_task(coro):  # noqa: ANN001, ANN202
        created_coroutines.append(coro)
        coro.close()
        return SimpleNamespace()

    record = {
        "execution_id": "exec-native",
        "task_id": "",
        "conversation_id": "sess-native",
        "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
        "state": "executing",
        "summary": "use the browser and create a report",
        "progress_summary": "Provider-native worker is running.",
        "bot_id": "nova",
    }
    with (
        patch(
            "thomas.server.chat_delegation.task_bot_runtime.create_execution",
            return_value={"execution_id": "exec-native"},
        ),
        patch("thomas.server.chat_delegation.task_bot_runtime.update_execution"),
        patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", return_value=record),
        patch("thomas.server.chat_delegation._run_agent_worker_supervised", new=_supervisor),
        patch("thomas.server.chat_delegation.asyncio.create_task", side_effect=_create_task),
    ):
        await chat_delegation._start_agent_worker_delegation(
            {},
            session_id="sess-native",
            prompt=(
                "Use browser.open and browser.extract, then fs.write_file agentic_report.md "
                "and verify it with fs.read_file."
            ),
            specialist_id="coding",
            bot=_BotStub(),
            emitter=emitter,
            repo_root=None,
        )

    instructions = captured["instructions"]
    assert "WEB CAPABILITY" in instructions
    assert "`browser.open`" in instructions
    assert "`browser.extract` with a CSS selector" in instructions
    assert "Never claim that browsing is outside your capabilities" in instructions
    assert "EXECUTION FIDELITY" in instructions
    assert "preserve exact requested filenames" in instructions
    assert "Never put bracketed placeholders" in instructions
    assert "Read back the exact requested artifact" in instructions
    assert captured["prompt"].startswith("Use browser.open and browser.extract")
    assert "preflight_events" not in captured
    assert "preflight_baseline" not in captured
    assert len(created_coroutines) == 1
    emitter.started.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_retries_use_fresh_internal_sessions() -> None:
    emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
    prompts: list[str] = []
    worker_sessions: list[str] = []

    async def _events():  # noqa: ANN202
        yield {
            "type": "model_runtime",
            "runtime": {
                "requested": {"profile": "test", "provider": "fixture", "model": "test-model"},
                "active": {"profile": "test", "provider": "fixture", "model": "test-model"},
                "attempts": [
                    {
                        "profile": "test",
                        "provider": "fixture",
                        "model": "test-model",
                        "status": "success",
                    }
                ],
            },
        }
        yield {"type": "tool_start", "name": "shell.exec"}
        yield {"type": "tool_output", "name": "shell.exec", "ok": True}
        yield {"type": "done"}

    def _worker_events(*_args, **kwargs):  # noqa: ANN202
        prompts.append(kwargs["prompt"])
        worker_sessions.append(kwargs["session_id"])
        return _events()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
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
                profile="test",
                model_id="test-model",
                autonomy_level=4,
            )

    assert len(prompts) == 3
    assert worker_sessions == [
        "exec-native-attempt-1",
        "exec-native-attempt-2",
        "exec-native-attempt-3",
    ]
    assert "no write tool was used" in prompts[1]
    assert "no write tool was used" in fail_execution.call_args.kwargs["summary"]
    emitter.failed.assert_awaited_once()
    emitter.completed.assert_not_awaited()
