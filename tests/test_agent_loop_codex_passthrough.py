import asyncio
import unittest

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.registry import ToolRegistry


class DummyCodexLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(
            name="codex",
            provider="codex",
            model="gpt-5.2-codex",
            context_window=2048,
            max_tokens=64,
        )

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        yield StreamEvent(type="token", data={"text": "hi"})
        yield StreamEvent(type="tool_call_start", data={"id": "t1", "name": "cmd /c echo hello"})
        yield StreamEvent(
            type="tool_call_end",
            data={
                "id": "t1",
                "name": "cmd /c echo hello",
                "arguments": "",
                "output": "hello\r\n",
                "exit_code": 0,
            },
        )
        yield StreamEvent(type="done", data={})


class TestAgentLoopCodexPassthrough(unittest.TestCase):
    def test_codex_tool_output_is_passthrough(self) -> None:
        cfg = AppConfig(
            models={"codex": ModelConfig(name="codex", provider="codex", model="gpt-5.2-codex")},
            default_model="codex",
        )
        tools = ToolRegistry()
        conversation: list[dict] = []
        agent = AgentLoop(cfg, DummyCodexLLM(), tools, conversation=conversation)

        async def run_once():
            events = []
            async for ev in agent.run("hello", tools_policy="never"):
                events.append(ev)
            return events

        events = asyncio.run(run_once())

        self.assertTrue(any(e.type == EventType.TOOL_RESULT for e in events))
        # Codex tools are executed by Codex; Thomas should not inject tool-role messages.
        self.assertEqual([m.get("role") for m in conversation], ["user", "assistant"])
        self.assertEqual(conversation[0].get("content"), "hello")
        self.assertEqual(conversation[1].get("content"), "hi")
