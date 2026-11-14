import inspect
import types
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


class _FakeMemoryCtx:
    working = ""
    episodic = ""
    semantic = ""
    total_tokens = 0


class _FakeMemoryCoordinator:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs

    async def refresh(self, **kwargs):  # noqa: ANN003
        _ = kwargs
        return _FakeMemoryCtx()

    async def capture_episode(self, **kwargs):  # noqa: ANN003
        _ = kwargs
        return None


class TestOrchestratorBrainStatus(unittest.IsolatedAsyncioTestCase):
    # RETIRED: test_background_status_reply_uses_active_task_state_directly.
    #
    # It passed dispatch_actionable=False and asserted the brain answered a
    # status question from a canned template without ever calling the model
    # (_dispatch_single.assert_not_awaited, plus the literal sentence
    # "Background work has completed in this thread."). That is a semantic route
    # chosen before the model runs, which CONTRIBUTING_AI.md "Semantic Intent
    # Ownership" forbids, and the assertion predates the doctrine that replaced
    # it: the canned expectation landed 2026-03-27 (580bc8fb) and was superseded
    # on 2026-06-14 by 0568447f, "no canned/instant replies", which added the
    # sibling test below. The parameter it steered was deleted with the
    # prompt-word classifiers on 2026-07-27 (69bbbab0).
    #
    # _summarize_background_status itself keeps its coverage in
    # test_orchestrator_brain_coverage.py and
    # test_orchestrator_brain_completion_report.py, so retiring this test drops
    # no assertion about that helper.

    async def test_background_actionable_reply_is_model_generated_not_canned(self):
        """An auto-background task does not get a canned 'task started' ack.

        Calvin: an instantaneous templated reply isn't the AI replying. The
        brain must call the model and surface its real words — not a
        hash-selected canned line.
        """
        brain = OrchestratorBrain(
            config=None,
            llm=None,
            memory_engine=None,
            registry=object(),
        )
        dispatcher = _FakeDispatcher()
        conversation = ConversationManager()
        model_reply = types.SimpleNamespace(ok=True, content="Sure — I'll get that going for you.", tokens_used=12)

        with (
            patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _FakeMemoryCoordinator),
            patch.object(
                OrchestratorBrain, "_dispatch_single", new=AsyncMock(return_value=model_reply)
            ) as dispatch_single,
        ):
            updated = await brain.process_message(
                session_id="sess-ack",
                conversation=conversation,
                prompt="Please set up Discord for Thomas.",
                dispatcher=dispatcher,
                mode="auto",
                active_tasks=[],
            )

        # The model WAS used — the defining difference from the old canned path.
        dispatch_single.assert_awaited()
        self.assertEqual(updated.last_assistant_message(), "Sure — I'll get that going for you.")
        self.assertTrue(dispatcher.done_payloads)
        # No longer the dedicated "background_ack" canned summary.
        self.assertNotEqual(dispatcher.done_payloads[-1].get("thinking_summary"), "background_ack")

    async def test_route_forcing_arguments_are_rejected_not_silently_ignored(self):
        """The removed controls must fail loudly if a caller tries to use them.

        This is the point of the change: dispatch_actionable=False used to be
        accepted and discarded, so a caller believed it had prevented a dispatch
        when it had not. Absent parameters raise TypeError instead of lying.
        """
        brain = OrchestratorBrain(
            config=None,
            llm=None,
            memory_engine=None,
            registry=object(),
        )
        for kwargs in ({"dispatch_actionable": False}, {"background_ack_only": True}):
            with self.subTest(argument=next(iter(kwargs))):
                with self.assertRaises(TypeError):
                    await brain.process_message(
                        session_id="sess-removed",
                        conversation=ConversationManager(),
                        prompt="anything",
                        dispatcher=_FakeDispatcher(),
                        **kwargs,
                    )

    async def test_is_first_message_is_still_accepted_for_the_live_chat_route(self):
        """thomas/server/routes/chat_v2.py passes is_first_message on every turn.

        It is caller state rather than a route control, and it is deliberately
        NOT removed alongside the two forced-route arguments: dropping it from
        this signature would raise TypeError on every live chat turn.
        """
        parameters = inspect.signature(OrchestratorBrain.process_message).parameters
        self.assertIn("is_first_message", parameters)
        self.assertNotIn("dispatch_actionable", parameters)
        self.assertNotIn("background_ack_only", parameters)

        brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=object())
        dispatcher = _FakeDispatcher()
        model_reply = types.SimpleNamespace(ok=True, content="Hello.", tokens_used=3)

        with (
            patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", _FakeMemoryCoordinator),
            patch.object(OrchestratorBrain, "_dispatch_single", new=AsyncMock(return_value=model_reply)),
        ):
            updated = await brain.process_message(
                session_id="sess-first",
                conversation=ConversationManager(),
                prompt="hi",
                dispatcher=dispatcher,
                mode="auto",
                is_first_message=True,
                active_tasks=[],
            )

        self.assertEqual(updated.last_assistant_message(), "Hello.")


if __name__ == "__main__":
    unittest.main()
