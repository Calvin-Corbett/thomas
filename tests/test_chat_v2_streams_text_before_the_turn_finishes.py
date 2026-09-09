"""/api/v2/chat must deliver reply text while the model is still working.

The unified shell reads this route's NDJSON incrementally; the flagship gap
(measured 2026-08-05) was 26-46s of typing dots then ONE paint. The specialist
fix streams sentences as the model produces them -- this test pins the layer
above: the ROUTE writes each emitted text event to the wire immediately, not
after ``process_message`` returns.

The proof is structural, not a timing race: the fake brain emits one text
event and then BLOCKS until the test releases it -- and the test releases it
only AFTER reading that text event off the open HTTP stream. If any layer
(dispatcher, StreamResponse, middleware) buffered text until turn completion,
the readline below would never return and the test would fail on its timeout,
because the brain can never finish until the line is read.
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


class _GatedStreamLLM:
    """A model whose stream pauses mid-reply until the test releases it.

    Used with the REAL OrchestratorBrain and REAL ReasoningSpecialist, so the
    full production path -- route, dispatcher, brain, specialist holdback --
    carries the sentences to the wire.
    """

    release: asyncio.Event

    def stream_chat(self, *, messages, tools=None):
        from thomas.core.llm_shared import StreamEvent

        _ = messages, tools

        async def _gen():
            yield StreamEvent(type="token", data={"text": "The first sentence lands on the wire. "})
            yield StreamEvent(type="token", data={"text": "The second one begins"})
            await _GatedStreamLLM.release.wait()
            yield StreamEvent(type="token", data={"text": " and finishes cleanly."})
            yield StreamEvent(type="done", data={})

        return _gen()


class _GatedBrain:
    """Streams the first sentence, then waits for the test to release it."""

    first_sentence = "The first sentence is on the wire. "
    rest = "The rest of the reply arrives after the gate."
    release: asyncio.Event

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001
        _ = session_id, kwargs
        await dispatcher.emit_text(_GatedBrain.first_sentence)
        await _GatedBrain.release.wait()
        await dispatcher.emit_text(_GatedBrain.rest)
        reply = _GatedBrain.first_sentence + _GatedBrain.rest
        return conversation.append_message("user", prompt).append_message("assistant", reply)


class TestChatV2StreamsTextBeforeTheTurnFinishes(AioHTTPTestCase):
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

    async def test_a_text_chunk_is_readable_while_the_brain_is_still_blocked(self):
        _GatedBrain.release = asyncio.Event()

        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _GatedBrain):
            resp = await self.client.post(
                "/api/v2/chat",
                json={"session_id": "sess-live-stream", "profile": "local", "message": "talk to me"},
            )
            self.assertEqual(resp.status, 200)

            first_text = None
            async def _read_until_text():
                nonlocal first_text
                while True:
                    line = await resp.content.readline()
                    if not line:
                        raise AssertionError("stream ended before any text event")
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "text":
                        first_text = event
                        return

            try:
                await asyncio.wait_for(_read_until_text(), timeout=15)
            except asyncio.TimeoutError:
                self.fail(
                    "No text event was readable while the turn was still running: "
                    "the route (or something under it) buffers the reply until "
                    "completion -- the one-paint chat this bundle removes."
                )

            # The brain is provably still blocked: only this test can release it.
            self.assertFalse(_GatedBrain.release.is_set())
            self.assertIn("first sentence", str(first_text.get("text") or ""))

            _GatedBrain.release.set()
            remainder = await resp.text()

        tail_events = [json.loads(line) for line in remainder.splitlines() if line.strip()]
        joined = "".join(str(e.get("text") or "") for e in tail_events if e.get("type") == "text")
        self.assertIn("rest of the reply", joined, "the post-gate text must still arrive")

    async def test_the_real_brain_and_specialist_stream_a_sentence_mid_generation(self):
        """Full production depth: only the MODEL is fake, and it is gated.

        The stream pauses after the second sentence begins; the released first
        sentence must be readable on the HTTP wire while the model is provably
        still mid-generation (the gate only opens after the read).
        """
        _GatedStreamLLM.release = asyncio.Event()

        async def _fake_init(app, **kwargs):  # noqa: ANN001, ANN003
            _ = app, kwargs
            return _GatedStreamLLM(), None, "local"

        with patch("thomas.server.routes.chat_v2.initialize_chat_v2_llm", _fake_init):
            resp = await self.client.post(
                "/api/v2/chat",
                json={
                    "session_id": "sess-real-depth-stream",
                    "profile": "local",
                    "message": "tell me two sentences",
                    "temporary": True,
                },
            )
            self.assertEqual(resp.status, 200)

            first_text = None

            async def _read_until_text():
                nonlocal first_text
                while True:
                    line = await resp.content.readline()
                    if not line:
                        raise AssertionError("stream ended before any text event")
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "text":
                        first_text = event
                        return

            try:
                await asyncio.wait_for(_read_until_text(), timeout=20)
            except asyncio.TimeoutError:
                self.fail(
                    "No text reached the wire while the model was mid-generation: "
                    "some layer between the specialist and the socket still "
                    "buffers the pass."
                )

            self.assertFalse(_GatedStreamLLM.release.is_set())
            self.assertIn("first sentence lands on the wire", str(first_text.get("text") or ""))

            _GatedStreamLLM.release.set()
            remainder = await resp.text()

        tail_events = [json.loads(line) for line in remainder.splitlines() if line.strip()]
        joined = "".join(str(e.get("text") or "") for e in tail_events if e.get("type") == "text")
        self.assertIn("finishes cleanly", joined, "the held tail must flush when the pass completes")


if __name__ == "__main__":
    unittest.main()
