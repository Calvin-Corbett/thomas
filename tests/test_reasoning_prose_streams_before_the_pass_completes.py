"""Chat prose must reach the wire while the model is still talking.

Measured 2026-08-05 on the live unified shell: every /api/v2/chat reply
rendered in ONE paint after a silent typing-dots wait -- 26-46 seconds of dead
dots for long answers. The client parses NDJSON incrementally and the
dispatcher writes each event as it is emitted, so the buffering lived in the
reasoning specialist: with tools offered (every live chat turn offers at least
the read tools), ``buffer_prose`` held EVERY token and emitted the whole pass
as a single text event after the provider stream finished.

The honesty law that buffer served stays absolute and is pinned elsewhere
(tests/test_send_task_tool.py::test_pre_tool_completion_claim_is_never_streamed):
prose immediately preceding a structured call -- the unearned completion claim
-- must never be streamed. The law needs only the TRAILING sentence held, not
the whole pass: once further prose has moved past a sentence boundary, an
arriving call can no longer make that earlier sentence the pre-call claim.

Pinned here:

* **prose streams mid-pass** -- with tools offered and no structured call, the
  first text event leaves the specialist BEFORE the provider stream finishes;
* **nothing is lost or duplicated** -- the streamed chunks join to exactly the
  full reply, and ``done.content`` matches;
* **the trailing claim still never streams** -- earlier narration in a pass
  that ends in a send_task call may stream (that is sight, not a claim), but
  the sentence adjacent to the call is suppressed exactly as before;
* **a boundless run still streams** -- prose with no sentence ends (a code
  block) is released past the holdback cap instead of quietly re-creating
  buffer-the-whole-pass.
"""

import unittest
from datetime import datetime, timedelta, timezone

from thomas.core.llm_shared import StreamEvent
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist


class _RecordingStreamLLM:
    """Yields scripted events while recording how far the stream has advanced.

    The async-generator pull model makes the proof deterministic: when the
    specialist yields a text event to its consumer, this fake has produced
    exactly the tokens pulled so far. If the specialist buffers the pass, the
    first text event only appears after ``produced`` already ends with the
    stream-done marker.
    """

    DONE = "<stream-done>"

    def __init__(self, scripts):
        self._scripts = scripts
        self.calls = 0
        self.produced = []

    def stream_chat(self, *, messages, tools=None):
        _ = messages, tools
        events = self._scripts[self.calls] if self.calls < len(self._scripts) else [StreamEvent(type="done")]
        self.calls += 1

        async def _gen():
            for event in events:
                if event.type == "token":
                    self.produced.append(str(event.data.get("text") or ""))
                yield event
            self.produced.append(self.DONE)

        return _gen()


def _contract(send_task=None):
    return DelegationContract(
        specialist_id="reasoning",
        task_description="x",
        allowed_tools={"reasoning"},
        timeout_seconds=0,
        # send_task wired means the structured-tool specs are offered -- the
        # exact live-chat condition under which the old code buffered the pass.
        input_context={"send_task": send_task or _noop_send_task},
    )


async def _noop_send_task(*, title, instructions, surface=""):
    _ = title, instructions, surface
    return None


def _token(text):
    return StreamEvent(type="token", data={"text": text})


async def _drive(llm, send_task=None):
    specialist = ReasoningSpecialist(config=None, llm=llm)
    token = CapabilityToken(
        specialist_id="reasoning",
        session_id="sess-stream",
        allowed_tools={"reasoning"},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    events = []
    produced_at_first_text = None
    async for event in specialist.execute(
        contract=_contract(send_task),
        token=token,
        prompt="tell me about the project",
        conversation_context=[],
        memory_context="",
    ):
        if event.get("type") == "text" and produced_at_first_text is None:
            produced_at_first_text = list(llm.produced)
        events.append(event)
    return events, produced_at_first_text


class TestProseStreamsBeforeThePassCompletes(unittest.IsolatedAsyncioTestCase):
    async def test_first_text_event_leaves_before_the_stream_finishes(self):
        llm = _RecordingStreamLLM(
            [
                [
                    _token("The first sentence lands early. "),
                    _token("The second sentence begins"),
                    _token(" and keeps going for a while. "),
                    _token("A third wraps the thought."),
                    StreamEvent(type="done"),
                ]
            ]
        )
        events, produced_at_first_text = await _drive(llm)

        self.assertIsNotNone(produced_at_first_text, "no text event was emitted at all")
        self.assertNotIn(
            llm.DONE,
            produced_at_first_text,
            "the first text event must reach the consumer while the provider "
            "stream is still producing -- emitting everything after the stream "
            "ends is the measured one-paint reply",
        )

        visible = "".join(str(e.get("text") or "") for e in events if e.get("type") == "text")
        full = (
            "The first sentence lands early. The second sentence begins"
            " and keeps going for a while. A third wraps the thought."
        )
        self.assertEqual(visible, full, "streaming must not lose or duplicate reply text")
        done = next(e for e in events if e.get("type") == "done")
        self.assertEqual(str(done.get("content") or ""), full)

    async def test_trailing_claim_before_a_call_still_never_streams(self):
        calls = []

        async def send_task(*, title, instructions, surface=""):
            calls.append(title)
            _ = instructions, surface

        llm = _RecordingStreamLLM(
            [
                [
                    _token("Let me get that moving for you. "),
                    _token("Handing this to the crew now. "),
                    _token("Done — I built all three files."),
                    StreamEvent(
                        type="tool_call_end",
                        data={
                            "id": "c1",
                            "name": "send_task",
                            "arguments": '{"title":"Build three files","instructions":"Build them"}',
                        },
                    ),
                    StreamEvent(type="done"),
                ],
                [
                    _token("The three builds are running now."),
                    StreamEvent(type="done"),
                ],
            ]
        )
        events, _ = await _drive(llm, send_task=send_task)
        visible = "".join(str(e.get("text") or "") for e in events if e.get("type") == "text")

        # The dispatch really happened, and the sentence adjacent to the call
        # -- the unearned completion claim -- never reached the wire.
        self.assertEqual(calls, ["Build three files"])
        self.assertNotIn("built all three", visible.lower())
        # Earlier narration that further prose had already moved past is
        # sight, not a claim, and may stream.
        self.assertIn("Let me get that moving for you.", visible)
        # The deterministic receipt stays the voice of the dispatch itself.
        self.assertIn("running now", visible)

    async def test_prose_without_sentence_ends_still_streams(self):
        # 26 chunks of 40 characters with no terminator anywhere: a code block
        # shape. The holdback cap must release it progressively rather than
        # quietly re-creating the whole-pass buffer for exactly the replies
        # where buffering hurts most.
        chunk = "x" * 40
        llm = _RecordingStreamLLM([[_token(chunk) for _ in range(26)] + [StreamEvent(type="done")]])
        events, produced_at_first_text = await _drive(llm)

        self.assertIsNotNone(produced_at_first_text, "no text event was emitted at all")
        self.assertNotIn(llm.DONE, produced_at_first_text)
        visible = "".join(str(e.get("text") or "") for e in events if e.get("type") == "text")
        self.assertEqual(visible, chunk * 26)


if __name__ == "__main__":
    unittest.main()
