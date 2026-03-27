import unittest

from thomas.chat.conversation import ConversationManager
from thomas.marketplace.orchestrator.brain import OrchestratorBrain


class _FakeMemoryContext:
    def to_system_injection(self) -> str:
        return ""


class _FakeDispatcher:
    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.agent_activity: list[dict] = []
        self.delegations: list[dict] = []

    async def emit_text(self, text: str) -> None:
        self.text_parts.append(str(text))

    async def emit(self, payload: dict) -> None:
        _ = payload

    async def emit_delegation(self, **payload) -> None:
        self.delegations.append(dict(payload))

    async def emit_agent_activity(self, **payload) -> None:
        self.agent_activity.append(dict(payload))


class _FakeSpecialist:
    capabilities = {"reasoning"}

    async def execute(self, **kwargs):  # noqa: ANN003
        _ = kwargs
        yield {"type": "text", "text": "Hello"}
        yield {"type": "text", "text": " there"}
        yield {"type": "done", "content": "Hello there", "iterations": 1}


class _FakeRegistry:
    specialist_ids = ["reasoning"]

    def __init__(self) -> None:
        self.executed: list[str] = []

    def get(self, specialist_id: str):
        if specialist_id == "reasoning":
            return _FakeSpecialist()
        return None

    def record_execution(self, specialist_id: str) -> None:
        self.executed.append(str(specialist_id))


class TestOrchestratorBrainStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_single_can_stream_text_events(self):
        registry = _FakeRegistry()
        brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=registry)
        dispatcher = _FakeDispatcher()

        result = await brain._dispatch_single(
            session_id="sess-1",
            specialist_id="reasoning",
            prompt="Say hello.",
            conversation=ConversationManager(),
            memory_ctx=_FakeMemoryContext(),
            dispatcher=dispatcher,
            thinking=type(
                "ThinkingStub",
                (),
                {"start": lambda *a, **k: None, "append": lambda *a, **k: None, "end": lambda *a, **k: None},
            )(),
            mode="auto",
            autonomy_level=3,
            stream_text_events=True,
        )

        self.assertEqual(dispatcher.text_parts, ["Hello", " there"])
        self.assertEqual(result.content, "Hello there")
        self.assertTrue(registry.executed)


if __name__ == "__main__":
    unittest.main()
