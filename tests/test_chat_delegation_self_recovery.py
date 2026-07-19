"""Tests for max-autonomy worker self-recovery.

Calvin's requirement: "if given a task he can't do he should be able to figure
it out when on max autonomy." At L4 a failed worker attempt feeds its failure
into a fresh attempt (bounded); below L4 it does a single pass and reports.
"""

import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from thomas.server import chat_delegation as cd
from thomas.server import chat_delegation_runner


def _model_runtime_event() -> dict[str, object]:
    return {
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


class _FakeEmitter:
    def __init__(self) -> None:
        self.completed_text: str | None = None
        self.failed_text: str | None = None
        self.progress_texts: list[str] = []

    async def progress(self, record, *, specialist_id, bot, text) -> None:
        self.progress_texts.append(text)

    async def completed(self, record, *, specialist_id, bot, text="") -> None:
        self.completed_text = text

    async def failed(self, record, *, specialist_id, bot, text) -> None:
        self.failed_text = text


def _scripted_events(scripts: list[list[dict]]):
    """Return an async-generator stand-in for run_agent_worker_events that plays
    one scripted attempt per call, plus a state dict counting invocations."""
    state = {"calls": 0, "closed": 0}

    async def gen(app, **kwargs):  # noqa: ANN001, ANN003
        idx = state["calls"]
        state["calls"] += 1
        try:
            yield _model_runtime_event()
            for event in scripts[min(idx, len(scripts) - 1)]:
                yield event
        finally:
            state["closed"] += 1

    return gen, state


class TestSelfRecovery(unittest.IsolatedAsyncioTestCase):
    async def _run(self, scripts, autonomy_level):
        emitter = _FakeEmitter()
        bot = types.SimpleNamespace(name="Taylor", id="taylor")
        gen, state = _scripted_events(scripts)
        with (
            patch.object(cd, "run_agent_worker_events", new=gen),
            patch.object(cd.task_bot_runtime, "update_execution", lambda *a, **k: None),
            patch.object(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "e", "summary": "s"}),
            patch.object(cd.task_bot_runtime, "complete_execution", lambda *a, **k: None),
            patch.object(cd.task_bot_runtime, "fail_execution", lambda *a, **k: None),
            patch.object(cd, "_snapshot_workspace_files", lambda *a, **k: []),
            patch.object(cd, "_normalize_record", lambda payload: dict(payload or {})),
        ):
            await cd._run_agent_worker(
                None,
                execution_id="e",
                prompt="do the thing",
                specialist_id="coding",
                bot=bot,
                emitter=emitter,
                instructions="inst",
                repo_root=Path("."),
                work_dir=None,
                profile="test",
                model_id="test-model",
                autonomy_level=autonomy_level,
            )
        self.assertEqual(state["closed"], state["calls"])
        return emitter, state

    async def test_l4_retries_then_succeeds(self):
        scripts = [
            [{"type": "error", "error": "missing tool foo"}],  # attempt 1 fails
            [{"type": "text", "text": "made it"}, {"type": "done"}],  # attempt 2 succeeds
        ]
        emitter, state = await self._run(scripts, autonomy_level=4)
        self.assertEqual(state["calls"], 2)  # retried exactly once
        self.assertEqual(emitter.completed_text, "made it")
        self.assertIsNone(emitter.failed_text)
        self.assertTrue(any("another approach" in p for p in emitter.progress_texts))

    async def test_l4_gives_up_after_budget(self):
        scripts = [[{"type": "error", "error": "always fails"}]]
        emitter, state = await self._run(scripts, autonomy_level=4)
        self.assertEqual(state["calls"], 3)  # full L4 budget exhausted
        self.assertIsNotNone(emitter.failed_text)
        self.assertIn("provider-native worker reported a retryable error", emitter.failed_text)
        self.assertNotIn("always fails", emitter.failed_text)

    async def test_below_l4_does_not_retry(self):
        scripts = [[{"type": "error", "error": "one shot only"}]]
        emitter, state = await self._run(scripts, autonomy_level=3)
        self.assertEqual(state["calls"], 1)  # single attempt at L3
        self.assertIsNotNone(emitter.failed_text)

    async def test_recovery_budget_helper(self):
        self.assertEqual(cd._self_recovery_attempts(4), 3)
        self.assertEqual(cd._self_recovery_attempts(3), 1)
        self.assertEqual(cd._self_recovery_attempts(0), 1)

    async def test_l4_retries_when_claimed_file_not_created(self):
        # M2: attempt claims it created a file but the workspace is empty + no tools
        # -> treat as a retryable failure (don't report a completion that didn't happen).
        scripts = [
            [{"type": "text", "text": "Created game.html with the snake game."}, {"type": "done"}],
            [{"type": "text", "text": "Done — wrote the answer in chat."}, {"type": "done"}],
        ]
        emitter, state = await self._run(scripts, autonomy_level=4)
        self.assertEqual(state["calls"], 2)  # retried because attempt 1 produced no file
        self.assertEqual(emitter.completed_text, "Done — wrote the answer in chat.")
        self.assertIsNone(emitter.failed_text)

    async def test_no_retry_when_only_thinking_mentions_a_file(self):
        # M2/M3-B: a worker that merely DISCUSSES creating a file in its chain-of-thought
        # but whose final line makes no claim must NOT be force-retried/failed.
        scripts = [
            [
                {"type": "text", "text": "I could create a results file, but the user just wants the number.\n"},
                {"type": "text", "text": "The answer is 42."},
                {"type": "done"},
            ]
        ]
        emitter, state = await self._run(scripts, autonomy_level=4)
        self.assertEqual(state["calls"], 1)  # no retry — the LAST line claims no file
        self.assertEqual(emitter.completed_text, "The answer is 42.")
        self.assertIsNone(emitter.failed_text)

    async def test_non_retryable_error_fails_immediately(self):
        # MR5: a deterministic terminal state (retryable=False) is not replayed at L4.
        scripts = [[{"type": "error", "error": "suspicious prompt denied", "retryable": False}]]
        emitter, state = await self._run(scripts, autonomy_level=4)
        self.assertEqual(state["calls"], 1)  # no retry despite L4
        self.assertIsNotNone(emitter.failed_text)
        self.assertIn("provider-native worker reported a non-retryable error", emitter.failed_text)
        self.assertNotIn("suspicious prompt denied", emitter.failed_text)

    async def test_user_cancellation_closes_the_active_worker_stream(self):
        emitter = _FakeEmitter()
        bot = types.SimpleNamespace(name="Taylor", id="taylor")
        gen, state = _scripted_events([[{"type": "done"}]])
        with (
            patch.object(cd, "run_agent_worker_events", new=gen),
            patch.object(cd.task_bot_runtime, "update_execution", lambda *a, **k: None),
            patch.object(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "e"}),
            patch.object(cd.task_bot_runtime, "is_cancel_requested", lambda *a, **k: True),
            patch.object(cd.task_bot_runtime, "fail_execution", lambda *a, **k: None),
            patch.object(cd, "_normalize_record", lambda payload: dict(payload or {})),
        ):
            await cd._run_agent_worker(
                None,
                execution_id="e",
                prompt="do the thing",
                specialist_id="coding",
                bot=bot,
                emitter=emitter,
                instructions="inst",
                repo_root=Path("."),
                autonomy_level=4,
            )
        self.assertEqual(state, {"calls": 1, "closed": 1})
        self.assertEqual(emitter.failed_text, "Cancelled by user.")

    async def test_exact_artifact_early_completion_closes_the_worker_stream(self):
        emitter = _FakeEmitter()
        bot = types.SimpleNamespace(name="Taylor", id="taylor")
        gen, state = _scripted_events(
            [
                [
                    {"type": "tool_start", "name": "fs.write_file"},
                    {"type": "tool_output", "name": "fs.write_file", "ok": True, "result_text": "Wrote report.md"},
                ]
            ]
        )
        finalize = AsyncMock()
        with (
            patch.object(cd, "run_agent_worker_events", new=gen),
            patch.object(chat_delegation_runner, "_finalize_worker_completion", finalize),
            patch.object(cd.task_bot_runtime, "update_execution", lambda *a, **k: None),
            patch.object(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "e"}),
            patch.object(cd, "_normalize_record", lambda payload: dict(payload or {})),
        ):
            await cd._run_agent_worker(
                None,
                execution_id="e",
                prompt="Create report.md.",
                specialist_id="coding",
                bot=bot,
                emitter=emitter,
                instructions="inst",
                repo_root=Path("."),
                autonomy_level=4,
            )
        self.assertEqual(state, {"calls": 1, "closed": 1})
        finalize.assert_awaited_once()

    async def test_setup_error_before_any_event_fails_immediately(self):
        # MR6: a config/setup error raised before any worker event is deterministic —
        # don't burn the L4 recovery budget retrying it.
        state = {"calls": 0}

        async def _raising(app, **kwargs):  # noqa: ANN001, ANN003
            state["calls"] += 1
            raise RuntimeError("no model configured")
            yield  # pragma: no cover - makes this an async generator

        emitter = _FakeEmitter()
        bot = types.SimpleNamespace(name="Taylor", id="taylor")
        with (
            patch.object(cd, "run_agent_worker_events", new=_raising),
            patch.object(cd.task_bot_runtime, "update_execution", lambda *a, **k: None),
            patch.object(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "e"}),
            patch.object(cd.task_bot_runtime, "complete_execution", lambda *a, **k: None),
            patch.object(cd.task_bot_runtime, "fail_execution", lambda *a, **k: None),
            patch.object(cd, "_snapshot_workspace_files", lambda *a, **k: []),
            patch.object(cd, "_normalize_record", lambda p: dict(p or {})),
        ):
            await cd._run_agent_worker(
                None,
                execution_id="e",
                prompt="x",
                specialist_id="coding",
                bot=bot,
                emitter=emitter,
                instructions="i",
                repo_root=Path("."),
                work_dir=None,
                autonomy_level=4,
            )
        self.assertEqual(state["calls"], 1)  # setup error not retried
        self.assertIsNotNone(emitter.failed_text)


if __name__ == "__main__":
    unittest.main()
