import unittest
from unittest.mock import AsyncMock, patch

from thomas.chat.conversation import ConversationManager
from thomas.marketplace.orchestrator.brain import OrchestratorBrain


class _FakeDispatcher:
    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.done_payloads: list[dict] = []

    async def emit_text(self, text: str) -> None:
        self.text_parts.append(str(text))

    async def emit_done(self, **payload) -> None:
        self.done_payloads.append(dict(payload))


class _FakeMemoryCoordinator:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def capture_episode(self, **kwargs):  # noqa: ANN003
        _ = kwargs
        return None


class TestOrchestratorBrainStatus(unittest.IsolatedAsyncioTestCase):
    async def test_background_status_reply_uses_active_task_state_directly(self):
        brain = OrchestratorBrain(
            config=None,
            llm=None,
            memory_engine=None,
            registry=object(),
        )
        dispatcher = _FakeDispatcher()
        conversation = ConversationManager()
        active_tasks = [
            {
                "execution_id": "exec-1",
                "session_id": "sess-1",
                "state": "completed",
                "summary": "Draft a detailed hour-by-hour Friday plan.",
                "last_progress": "Background execution completed.",
                "backend_type": "provider_native",
            }
        ]

        with (
            patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _FakeMemoryCoordinator),
            patch.object(OrchestratorBrain, "_dispatch_single", new=AsyncMock()) as dispatch_single,
        ):
            updated = await brain.process_message(
                session_id="sess-1",
                conversation=conversation,
                prompt="What is the status of the background work?",
                dispatcher=dispatcher,
                mode="auto",
                active_tasks=active_tasks,
                active_task_digest="Background work in this chat:\n- provider task",
                dispatch_actionable=False,
            )

        dispatch_single.assert_not_awaited()
        self.assertIn("Background work has completed in this thread.", "".join(dispatcher.text_parts))
        self.assertIn("Draft a detailed hour-by-hour Friday plan.", updated.last_assistant_message() or "")
        self.assertTrue(dispatcher.done_payloads)
        self.assertEqual(dispatcher.done_payloads[-1].get("thinking_summary"), "background_status")

    async def test_background_ack_reply_skips_llm_and_emits_short_started_message(self):
        brain = OrchestratorBrain(
            config=None,
            llm=None,
            memory_engine=None,
            registry=object(),
        )
        dispatcher = _FakeDispatcher()
        conversation = ConversationManager()

        with (
            patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _FakeMemoryCoordinator),
            patch.object(OrchestratorBrain, "_dispatch_single", new=AsyncMock()) as dispatch_single,
        ):
            updated = await brain.process_message(
                session_id="sess-ack",
                conversation=conversation,
                prompt="Please set up Discord for Thomas.",
                dispatcher=dispatcher,
                mode="auto",
                active_tasks=[],
                dispatch_actionable=False,
                background_ack_only=True,
            )

        dispatch_single.assert_not_awaited()
        self.assertEqual("".join(dispatcher.text_parts), "Working on that now.")
        self.assertEqual(updated.last_assistant_message(), "Working on that now.")
        self.assertTrue(dispatcher.done_payloads)
        self.assertEqual(dispatcher.done_payloads[-1].get("thinking_summary"), "background_ack")


if __name__ == "__main__":
    unittest.main()
