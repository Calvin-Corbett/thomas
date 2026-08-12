"""Regression tests for reporting finished background work back into chat.

The live bug (Calvin, 2026-06-16): a worker created `livecheck.txt`, the task
card flipped to completed, but the chat agent kept saying "I don't have the
result back." Root cause: the completion note was shown to the USER as a prefix
but never injected into the MODEL's context, and it was only wired into the
casual branch — so the model contradicted the delivered line, and any non-casual
follow-up dropped the result entirely.

These tests lock the fix: the completion is (a) injected into the model's
context so it reports in its own voice, (b) delivered on every routing branch,
and (c) reported exactly once.
"""

import types
import unittest
from unittest.mock import AsyncMock, patch

from thomas.chat.conversation import ConversationManager
from thomas.marketplace.orchestrator import brain as brain_mod
from thomas.marketplace.orchestrator.brain import OrchestratorBrain


class _FakeDispatcher:
    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.done_payloads: list[dict] = []

    async def emit_text(self, text: str) -> None:
        self.text_parts.append(str(text))

    async def emit_done(self, **payload) -> None:
        self.done_payloads.append(dict(payload))

    async def emit(self, event) -> None:  # thinking events
        return None

    async def emit_memory_refresh(self, **kwargs) -> None:
        return None


class _FakeMemoryCtx:
    def __init__(self) -> None:
        self.working = ""
        self.episodic = ""
        self.semantic = ""
        self.total_tokens = 0

    def to_system_injection(self) -> str:
        return self.working


class _FakeMemoryCoordinator:
    def __init__(self, *args, **kwargs) -> None:
        _ = (args, kwargs)

    async def refresh(self, **kwargs):  # noqa: ANN003
        _ = kwargs
        return _FakeMemoryCtx()

    async def capture_episode(self, **kwargs):  # noqa: ANN003
        _ = kwargs
        return None


_COMPLETED_TASK = {
    "execution_id": "exec-live",
    "session_id": "sess-live",
    "state": "completed",
    "summary": "Create a file named livecheck.txt",
    "last_progress": "Created livecheck.txt",
    "bot_name": "Taylor",
    "backend_type": "provider_native",
}


def _brain() -> OrchestratorBrain:
    return OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=object())


class TestCompletionReport(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        brain_mod._reported_completions.clear()

    async def test_casual_reply_injects_completion_into_model_context(self) -> None:
        """The model SEES the finished task (the core fix) and authors the reply
        itself — no canned 'Quick update' prefix is forced in front of it."""
        captured: dict = {}

        async def _capture(**kwargs):  # noqa: ANN003
            captured["memory_ctx"] = kwargs.get("memory_ctx")
            return types.SimpleNamespace(
                ok=True, content="Yep — Taylor just created livecheck.txt. Done!", tokens_used=7
            )

        dispatcher = _FakeDispatcher()
        with (
            patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _FakeMemoryCoordinator),
            patch.object(OrchestratorBrain, "_dispatch_single", new=AsyncMock(side_effect=_capture)),
        ):
            updated = await _brain().process_message(
                session_id="sess-live",
                conversation=ConversationManager(),
                prompt="are you done?",
                dispatcher=dispatcher,
                mode="auto",
                active_tasks=[dict(_COMPLETED_TASK)],
            )

        ctx = captured.get("memory_ctx")
        self.assertIsNotNone(ctx, "model was never dispatched")
        self.assertIn("Background work just finished", ctx.working)
        self.assertIn("Create a file named livecheck.txt", ctx.working)
        # Reply is the model's own words; no forced canned prefix on the model path.
        self.assertEqual(updated.last_assistant_message(), "Yep — Taylor just created livecheck.txt. Done!")
        self.assertNotIn("Quick update", "".join(dispatcher.text_parts))

    async def test_completion_reported_once_not_repeated(self) -> None:
        """A finished task is announced exactly once across turns (dedup)."""

        async def _echo(**kwargs):  # noqa: ANN003
            ctx = kwargs.get("memory_ctx")
            saw = "Background work just finished" in (ctx.working if ctx else "")
            return types.SimpleNamespace(ok=True, content=("REPORTED" if saw else "nothing-new"), tokens_used=1)

        with (
            patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _FakeMemoryCoordinator),
            patch.object(OrchestratorBrain, "_dispatch_single", new=AsyncMock(side_effect=_echo)),
        ):
            brain = _brain()
            first = await brain.process_message(
                session_id="sess-live",
                conversation=ConversationManager(),
                prompt="hey",
                dispatcher=_FakeDispatcher(),
                mode="auto",
                active_tasks=[dict(_COMPLETED_TASK)],
            )
            second = await brain.process_message(
                session_id="sess-live",
                conversation=first,
                prompt="hey again",
                dispatcher=_FakeDispatcher(),
                mode="auto",
                active_tasks=[dict(_COMPLETED_TASK)],
            )

        self.assertEqual(first.last_assistant_message(), "REPORTED")
        self.assertEqual(second.last_assistant_message(), "nothing-new")

    async def test_new_request_keeps_finished_work_in_model_context(self) -> None:
        """Prompt wording cannot route around factual completion context."""
        dispatcher = _FakeDispatcher()
        captured: dict = {}

        async def _single(**kwargs):  # noqa: ANN003
            captured["memory_ctx"] = kwargs.get("memory_ctx")
            return types.SimpleNamespace(
                ok=True, content="On the new thing now.", tokens_used=3, tool_calls=[], iterations=1
            )

        with (
            patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _FakeMemoryCoordinator),
            patch.object(OrchestratorBrain, "_dispatch_single", new=AsyncMock(side_effect=_single)),
        ):
            updated = await _brain().process_message(
                session_id="sess-live",
                conversation=ConversationManager(),
                prompt="now build me a snake game",
                dispatcher=dispatcher,
                mode="max",
                active_tasks=[dict(_COMPLETED_TASK)],
            )

        self.assertIn("Background work just finished", captured["memory_ctx"].working)
        self.assertEqual(updated.last_assistant_message(), "On the new thing now.")


class TestDurableDedup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        brain_mod._reported_completions.clear()

    async def test_already_reported_row_is_not_re_announced(self):
        """A completion already persisted as reported (e.g. before a restart) is
        not surfaced to the model again."""
        captured: dict = {}

        async def _capture(**kwargs):  # noqa: ANN003
            captured["memory_ctx"] = kwargs.get("memory_ctx")
            return types.SimpleNamespace(ok=True, content="hi there", tokens_used=1)

        task = dict(_COMPLETED_TASK)
        task["reported_to_chat_at"] = "2026-06-16T00:00:00+00:00"
        with (
            patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _FakeMemoryCoordinator),
            patch("thomas.marketplace.orchestrator.brain._mark_completion_reported") as mark,
            patch.object(OrchestratorBrain, "_dispatch_single", new=AsyncMock(side_effect=_capture)),
        ):
            await _brain().process_message(
                session_id="sess-live",
                conversation=ConversationManager(),
                prompt="hi",
                dispatcher=_FakeDispatcher(),
                mode="auto",
                active_tasks=[task],
            )

        ctx = captured.get("memory_ctx")
        self.assertNotIn("Background work just finished", ctx.working)
        mark.assert_not_called()

    async def test_fresh_completion_persists_the_flag(self):
        async def _capture(**kwargs):  # noqa: ANN003
            return types.SimpleNamespace(ok=True, content="ok", tokens_used=1)

        with (
            patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _FakeMemoryCoordinator),
            patch("thomas.marketplace.orchestrator.brain._mark_completion_reported") as mark,
            patch.object(OrchestratorBrain, "_dispatch_single", new=AsyncMock(side_effect=_capture)),
        ):
            await _brain().process_message(
                session_id="sess-live",
                conversation=ConversationManager(),
                prompt="hi",
                dispatcher=_FakeDispatcher(),
                mode="auto",
                active_tasks=[dict(_COMPLETED_TASK)],
            )

        mark.assert_called_once_with("exec-live")


class TestStatusSummaryReportsCompleted(unittest.TestCase):
    def test_reports_completed_even_while_another_runs(self):
        # M1 complementary: the status summary must surface a FINISHED task even when
        # another task is still running (the old early-return dropped it -> silent loss).
        from thomas.marketplace.orchestrator.brain import _summarize_background_status

        rows = [
            {"state": "executing", "summary": "build X", "last_progress": "working on it"},
            {"state": "completed", "summary": "make Y", "last_progress": "Created y.txt"},
        ]
        s = _summarize_background_status(rows)
        self.assertIn("running", s.lower())  # the active one
        self.assertIn("make Y", s)  # the COMPLETED one is NOT dropped
        self.assertIn("Created y.txt", s)

    def test_surfaces_blocked_row_alongside_terminal_rows(self):
        # Round-4 M1: a blocked/awaiting-proof row must not be dropped when completed/
        # failed rows coexist.
        from thomas.marketplace.orchestrator.brain import _summarize_background_status

        s = _summarize_background_status(
            [
                {"state": "completed", "summary": "Done thing"},
                {"state": "blocked", "summary": "Stuck thing", "last_progress": "needs key"},
            ]
        )
        self.assertIn("Done thing", s)
        self.assertIn("Stuck thing", s)
        self.assertIn("needs attention", s.lower())


class TestModelOwnedCompletionMark(unittest.IsolatedAsyncioTestCase):
    """Round-4 M3: on the status branch, mark reported ONLY the fresh completions the
    summary actually displayed. A fresh completion crowded past the displayed window
    must stay unreported (so a later turn delivers it) — never marked-but-not-shown."""

    async def asyncSetUp(self) -> None:
        brain_mod._reported_completions.clear()

    async def test_status_words_do_not_bypass_model_and_fresh_context_is_marked(self) -> None:
        # 4 already-reported completed rows (ordered first) + 2 fresh ones. The summary
        # shows the first 5 completed -> {4 reported, fresh-1}. fresh-2 is crowded out.
        reported = [
            {
                "execution_id": f"rep-{i}",
                "session_id": "sess-live",
                "state": "completed",
                "summary": f"reported {i}",
                "reported_to_chat_at": "2026-06-16T00:00:00+00:00",
            }
            for i in range(1, 5)
        ]
        fresh = [
            {"execution_id": "fresh-1", "session_id": "sess-live", "state": "completed", "summary": "fresh one"},
            {"execution_id": "fresh-2", "session_id": "sess-live", "state": "completed", "summary": "fresh two"},
        ]
        marked: list[str] = []
        captured: dict = {}

        async def _capture(**kwargs):  # noqa: ANN003
            captured["memory_ctx"] = kwargs.get("memory_ctx")
            return types.SimpleNamespace(ok=True, content="I can see the current task state.", tokens_used=1)

        with (
            patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _FakeMemoryCoordinator),
            patch(
                "thomas.marketplace.orchestrator.brain._mark_completion_reported",
                side_effect=lambda eid: marked.append(eid),
            ),
            patch.object(OrchestratorBrain, "_dispatch_single", new=AsyncMock(side_effect=_capture)),
        ):
            await _brain().process_message(
                session_id="sess-live",
                conversation=ConversationManager(),
                prompt="what is the status of the background worker?",
                dispatcher=_FakeDispatcher(),
                mode="auto",
                active_tasks=reported + fresh,
            )

        self.assertIn("fresh one", captured["memory_ctx"].working)
        self.assertIn("fresh two", captured["memory_ctx"].working)
        self.assertEqual(set(marked), {"fresh-1", "fresh-2"})
        # Already-reported rows are never re-marked.
        self.assertFalse(any(m.startswith("rep-") for m in marked))


if __name__ == "__main__":
    unittest.main()
