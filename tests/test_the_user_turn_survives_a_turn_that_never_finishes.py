"""The user's message must be in the session store the moment it is accepted.

Measured 2026-08-05, live server: /api/chats listed 476 chats and not one of
them contained the message the user had just sent, because the ONLY
``session_store.save`` for a turn ran after ``brain.process_message`` returned.
A tab abandoned mid-reply (aiohttp cancels the handler task), a model crash, or
a lost connection erased the entire turn -- the user's own words included.

Three behaviours pinned here, each against the real /api/v2/chat route with the
real ``SessionStore``:

* **persist-at-send** -- while the model is still thinking (the fake brain
  blocks on an event), the store already holds the chat with the user turn.
* **no duplicate** -- the send-time save must not double the user message once
  the turn completes normally: ``process_message`` appends the user turn
  itself, so the route strips the pending copy before handing the model the
  reloaded conversation.
* **salvage on failure** -- a turn that dies mid-reply leaves the user turn
  plus whatever reply text had already streamed, marked ``interrupted`` rather
  than silently vanishing.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE


def _parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if line:
            out.append(json.loads(line))
    return out


class _BlockingBrain:
    """A brain that signals when the turn starts and waits to be released."""

    started: asyncio.Event
    release: asyncio.Event

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        _BlockingBrain.started.set()
        await _BlockingBrain.release.wait()
        display = kwargs.get("display_prompt")
        updated = conversation.append_message("user", display if display is not None else prompt)
        reply = "Done -- moved it to 9."
        await dispatcher.emit_text(reply)
        return updated.append_message("assistant", reply)


class _PartialThenBoomBrain:
    """A brain that streams a partial reply and then dies mid-turn."""

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        _ = session_id, conversation, prompt, kwargs
        await dispatcher.emit_text("Here is the fir")
        raise RuntimeError("model died mid-reply")


class TestUserTurnSurvivesAnUnfinishedTurn(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._environment = patch.dict(
            "os.environ",
            {"THOMAS_DB_PATH": f"{self._tmpdir.name}/preferences.db"},
        )
        self._environment.start()

    def tearDown(self) -> None:
        try:
            self._environment.stop()
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={
                "local": ModelConfig(
                    name="local",
                    provider="openai_compat",
                    base_url="http://127.0.0.1:11434/v1",
                    model="dummy",
                )
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_the_user_turn_is_stored_before_the_reply_exists(self):
        _BlockingBrain.started = asyncio.Event()
        _BlockingBrain.release = asyncio.Event()
        sid = "sess-durability-pending"
        prompt = "change tuesday to 9"

        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _BlockingBrain):
            resp = await self.client.post(
                "/api/v2/chat",
                json={"session_id": sid, "profile": "local", "message": prompt},
            )
            self.assertEqual(resp.status, 200)
            # The model is still "thinking" -- the reply does not exist yet.
            await asyncio.wait_for(_BlockingBrain.started.wait(), timeout=10)

            store = self.app[APP_SESSION_STORE]
            conversation = await store.load(sid)
            self.assertIsNotNone(
                conversation,
                "The chat must be in the session store at SEND time, not only after the reply completes.",
            )
            messages = conversation.get_messages()
            user_turns = [m for m in messages if m.get("role") == "user" and m.get("content") == prompt]
            self.assertEqual(
                len(user_turns),
                1,
                f"Expected exactly one stored user turn mid-generation, saw messages: {messages}",
            )
            self.assertFalse(
                any(m.get("role") == "assistant" for m in messages),
                "No reply exists yet, so none may be stored yet.",
            )

            # Let the turn finish and drain the stream so the final save runs.
            _BlockingBrain.release.set()
            body = await resp.text()

        events = _parse_ndjson(body)
        self.assertTrue(any(evt.get("type") == "text" for evt in events))

        conversation = await self.app[APP_SESSION_STORE].load(sid)
        self.assertIsNotNone(conversation)
        messages = conversation.get_messages()
        user_turns = [m for m in messages if m.get("role") == "user" and m.get("content") == prompt]
        self.assertEqual(
            len(user_turns),
            1,
            f"The send-time save must not duplicate the user turn after completion: {messages}",
        )
        self.assertTrue(
            any(m.get("role") == "assistant" and "moved it to 9" in str(m.get("content")) for m in messages),
            f"The completed reply must replace the pending state, saw: {messages}",
        )

    async def test_a_turn_that_dies_mid_reply_keeps_the_user_turn_and_partial_text(self):
        sid = "sess-durability-boom"
        prompt = "summarize the quarterly report"

        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _PartialThenBoomBrain):
            resp = await self.client.post(
                "/api/v2/chat",
                json={"session_id": sid, "profile": "local", "message": prompt},
            )
            self.assertEqual(resp.status, 200)
            await resp.text()

        conversation = await self.app[APP_SESSION_STORE].load(sid)
        self.assertIsNotNone(
            conversation,
            "A failed turn must still leave the chat in the store -- the user typed it.",
        )
        messages = conversation.get_messages()
        self.assertTrue(
            any(m.get("role") == "user" and m.get("content") == prompt for m in messages),
            f"The user turn must survive the failure, saw: {messages}",
        )
        partials = [m for m in messages if m.get("role") == "assistant"]
        self.assertEqual(len(partials), 1, f"Expected the streamed partial reply to be saved, saw: {messages}")
        self.assertEqual(partials[0].get("content"), "Here is the fir")
        metadata = partials[0].get("metadata") or {}
        self.assertTrue(
            metadata.get("interrupted"),
            "A salvaged partial reply must be MARKED interrupted, never passed off as a finished answer.",
        )


if __name__ == "__main__":
    unittest.main()
