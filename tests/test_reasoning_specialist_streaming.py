import unittest

from thomas.core.llm_shared import StreamEvent
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist


class _FakeStreamingLLM:
    async def stream_chat(self, messages, tools=None):  # noqa: ANN001
        _ = messages
        _ = tools
        yield StreamEvent(type="token", data={"text": "Hello"})
        yield StreamEvent(type="token", data={"text": " there"})
        yield StreamEvent(type="done", data={})


class TestReasoningSpecialistStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_reasoning_specialist_streams_token_events(self):
        specialist = ReasoningSpecialist(config=None, llm=_FakeStreamingLLM(), tools=None)
        contract = DelegationContract(specialist_id="reasoning")
        token = CapabilityToken(specialist_id="reasoning", session_id="sess-1")

        events = []
        async for event in specialist.execute(
            contract=contract,
            token=token,
            prompt="Say hello.",
            conversation_context=[],
            memory_context="",
        ):
            events.append(event)

        text_chunks = [str(event.get("text") or "") for event in events if event.get("type") == "text"]
        self.assertEqual(text_chunks, ["Hello", " there"])
        done = next(event for event in events if event.get("type") == "done")
        self.assertEqual(str(done.get("content") or ""), "Hello there")


if __name__ == "__main__":
    unittest.main()
