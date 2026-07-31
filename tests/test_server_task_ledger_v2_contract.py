from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.app_keys import APP_TASK_LEDGER


def _parse_ndjson(blob: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in blob.splitlines() if line.strip()]


async def _complete_message(
    _brain: Any,
    session_id: str,
    conversation: Any,
    prompt: str,
    dispatcher: Any,
    **_kwargs: Any,
) -> Any:
    reply = "Completed and verified."
    conversation = conversation.append_message("user", prompt).append_message("assistant", reply)
    await dispatcher.emit_text(reply)
    await dispatcher.emit_done(session_id=session_id, conversation_version=conversation.version)
    return conversation


async def _request_missing_input(
    _brain: Any,
    session_id: str,
    conversation: Any,
    prompt: str,
    dispatcher: Any,
    **_kwargs: Any,
) -> Any:
    reply = "I need your API key before continuing."
    conversation = conversation.append_message("user", prompt).append_message("assistant", reply)
    await dispatcher.emit_text(reply)
    await dispatcher.emit_done(session_id=session_id, conversation_version=conversation.version)
    return conversation


async def _fail_message(
    _brain: Any,
    _session_id: str,
    _conversation: Any,
    _prompt: str,
    _dispatcher: Any,
    **_kwargs: Any,
) -> Any:
    raise RuntimeError("provider-secret-error-detail")


class TestTaskLedgerV2PublicContract(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        return create_app(
            AppConfig(
                models={"local": ModelConfig(name="local", model="dummy")},
                default_model="local",
                memory=MemoryConfig(root=self._tmpdir.name),
                server=ServerConfig(access_mode="local"),
            )
        )

    async def _post_chat(
        self,
        *,
        session_id: str,
        message: str,
        processor: Callable[..., Any],
        **payload: Any,
    ) -> list[dict[str, Any]]:
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain.process_message", processor):
            response = await self.client.post(
                "/api/chat",
                json={
                    "session_id": session_id,
                    "profile": "local",
                    "mode": "fast",
                    "message": message,
                    **payload,
                },
            )
            self.assertEqual(response.status, 200)
            body = await response.text()
        return _parse_ndjson(body)

    async def _current(self, session_id: str) -> dict[str, Any]:
        response = await self.client.get(f"/api/task-ledger/current?session_id={session_id}")
        self.assertEqual(response.status, 200)
        return await response.json()

    async def _history(self, session_id: str) -> dict[str, Any]:
        response = await self.client.get(f"/api/task-ledger/history?session_id={session_id}&limit=10")
        self.assertEqual(response.status, 200)
        return await response.json()

    async def test_chat_request_records_in_progress_then_complete_and_keeps_followup_goal(self) -> None:
        session_id = "v2-ledger-complete"
        events = await self._post_chat(
            session_id=session_id,
            message="Build the verified report",
            processor=_complete_message,
        )
        self.assertEqual([event["type"] for event in events].count("done"), 1)

        current = await self._current(session_id)
        self.assertEqual(current["state"]["active_goal"], "Build the verified report")
        self.assertEqual(current["state"]["status"], "complete")
        self.assertEqual(current["state"]["last_progress"], "Completed and verified.")

        history = (await self._history(session_id))["history"]
        self.assertEqual([event["status"] for event in history], ["complete", "in_progress"])
        self.assertEqual([event["source"] for event in history], ["chat_v2.done", "chat_v2.request"])

        # A second turn re-titles the goal from its own text. This asserted that
        # "do it" was recognised as a continuation and left the goal as "Build
        # the verified report" -- which required reading the wording to tell an
        # acknowledgement from a new request. `derive_active_goal` now says so at
        # the line: "Retained for compatibility only. Prompt wording never
        # decides whether a turn is an acknowledgement or a follow-up."
        # `current_goal` survives only when the new text is empty.
        await self._post_chat(
            session_id=session_id,
            message="do it",
            processor=_complete_message,
        )
        followup = await self._current(session_id)
        self.assertEqual(
            followup["state"]["active_goal"],
            "Do it",
            "the ledger inferred from wording that this turn continued the "
            "previous goal; that inference was removed in 69bbbab0",
        )
        followup_history = (await self._history(session_id))["history"]
        self.assertEqual(
            [event["status"] for event in followup_history],
            ["complete", "in_progress", "complete", "in_progress"],
        )

    async def test_a_reply_asking_for_input_is_not_classified_from_its_prose(self) -> None:
        """The ledger reads the runtime's terminal event, never the reply text.

        This asserted the opposite until 2026-07-31: that a reply reading "I
        need your API key before continuing" produced ``status="blocked"`` and
        ``missing_inputs=["API key"]``. That was a prompt classifier, and
        69bbbab0 ("land model-owned routing, removing the prompt classifiers")
        deleted the whole family of them on purpose -- conversational judgment
        now comes from the frontier model calling a structured tool, and
        deterministic code "may not invent the request". `record_chat_task_finished`
        says so in its own docstring: "Persist success from the runtime terminal
        event, never from reply prose."

        So the test was pinning removed behaviour and had been red ever since.
        It is rewritten rather than deleted because the contract it guards is
        worth stating explicitly: prose must NOT move the ledger.

        KNOWN GAP, recorded rather than papered over. A turn where Thomas stops
        and asks for something is recorded ``complete``, because the structured
        replacement -- a tool the model calls to declare itself blocked -- does
        not exist yet. Re-adding a regex over the reply would recreate exactly
        what was removed, so the fix belongs on the tool side. `blocked` today
        comes only from a real route failure, which
        `test_chat_route_failure_records_safe_blocked_state_without_leaking_detail`
        covers.
        """

        session_id = "v2-ledger-blocked"
        await self._post_chat(
            session_id=session_id,
            message="Publish the report",
            processor=_request_missing_input,
        )

        current = await self._current(session_id)
        self.assertEqual(current["state"]["active_goal"], "Publish the report")
        self.assertEqual(
            current["state"]["status"],
            "complete",
            "the ledger classified a turn from the wording of its reply; prompt "
            "classifiers were removed in 69bbbab0 and must not come back",
        )
        self.assertEqual(current["state"]["missing_inputs"], [])

        history = (await self._history(session_id))["history"]
        self.assertEqual([event["status"] for event in history], ["complete", "in_progress"])
        self.assertEqual([event["source"] for event in history], ["chat_v2.done", "chat_v2.request"])

    async def test_chat_route_failure_records_safe_blocked_state_without_leaking_detail(self) -> None:
        session_id = "v2-ledger-error"
        events = await self._post_chat(
            session_id=session_id,
            message="Run the fragile task",
            processor=_fail_message,
        )
        error_events = [event for event in events if event.get("type") == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0]["error"], "Thomas could not complete this chat turn safely.")
        self.assertNotIn("provider-secret-error-detail", json.dumps(events))

        current = await self._current(session_id)
        self.assertEqual(current["state"]["status"], "blocked")
        self.assertEqual(current["state"]["missing_inputs"], [])
        self.assertEqual(current["state"]["last_progress"], "Thomas could not complete this chat turn safely.")

        history = (await self._history(session_id))["history"]
        self.assertEqual([event["status"] for event in history], ["blocked", "in_progress"])
        self.assertEqual([event["source"] for event in history], ["chat_v2.error", "chat_v2.request"])
        self.assertNotIn("provider-secret-error-detail", json.dumps(history))

    @unittest.expectedFailure
    async def test_max_review_remains_in_progress_while_background_work_is_pending(self) -> None:
        """Held open deliberately: the feature this guards is currently gone.

        69bbbab0 records it as a known loss, in the owner's words: "Exhaustive
        (Max) no longer runs the crew and fresh graders. That flag read the
        effort DIAL, not prose, and went as collateral. I restored it and backed
        the restoration out: done is emitted inside brain.process_message, so
        the route cannot attach max_review_pending without redesigning the
        stream contract, and a half-restoration leaves the ledger in_progress
        after the UI already saw done -- the zombie-task bug.
        record_chat_task_pending currently has no caller."

        So this fails twice over: `chat_v2.effective_effort` no longer exists to
        patch, and nothing would emit `chat_v2.pending` if it did.

        Kept as an expected failure rather than deleted, and NOT loosened to
        match today's behaviour, because unlike the two tests above this one
        does not describe a decision -- it describes something the owner wants
        back. unittest's expectedFailure reports an unexpected SUCCESS as a
        failure, so the day someone gives `record_chat_task_pending` a caller,
        this test says so instead of sitting silently green.
        """

        session_id = "v2-ledger-max-pending"
        with (
            patch("thomas.server.routes.chat_v2.effective_effort", return_value="max"),
            patch(
                "thomas.server.routes.chat_v2.start_background_delegation",
                AsyncMock(return_value={"execution_id": "exec-ledger-max"}),
            ),
        ):
            response = await self.client.post(
                "/api/chat",
                json={
                    "session_id": session_id,
                    "profile": "local",
                    "mode": "max",
                    "message": "Build and freshly grade the report",
                },
            )
            self.assertEqual(response.status, 200)
            events = _parse_ndjson(await response.text())

        done_events = [event for event in events if event.get("type") == "done"]
        self.assertEqual(len(done_events), 1)
        self.assertTrue(done_events[0]["max_review_pending"])

        current = await self._current(session_id)
        self.assertEqual(current["state"]["status"], "in_progress")
        self.assertIn("Max review is running", current["state"]["last_progress"])
        history = (await self._history(session_id))["history"]
        self.assertEqual([event["status"] for event in history], ["in_progress", "in_progress"])
        self.assertEqual([event["source"] for event in history], ["chat_v2.pending", "chat_v2.request"])

    async def test_task_ledger_storage_failure_does_not_break_chat_turn(self) -> None:
        ledger = self.app[APP_TASK_LEDGER]
        with patch.object(ledger, "update", side_effect=OSError("task-ledger-disk-unavailable")):
            events = await self._post_chat(
                session_id="v2-ledger-storage-failure",
                message="Complete this despite telemetry failure",
                processor=_complete_message,
            )

        self.assertEqual([event["type"] for event in events].count("done"), 1)
        self.assertFalse(any(event.get("type") == "error" for event in events))

    async def test_temporary_chat_does_not_persist_task_ledger_state(self) -> None:
        session_id = "v2-ledger-temporary"
        await self._post_chat(
            session_id=session_id,
            message="Handle this without retention",
            processor=_complete_message,
            temporary=True,
        )

        current = await self._current(session_id)
        self.assertIsNone(current["state"])
        self.assertEqual((await self._history(session_id))["history"], [])


if __name__ == "__main__":
    unittest.main()
