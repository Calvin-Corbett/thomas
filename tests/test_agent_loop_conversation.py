from __future__ import annotations

import asyncio
import unittest
from typing import Any

from thomas.agent.loop import AgentLoop
from thomas.agent.prompt_templates import build_route_system_prompt
from thomas.agent.response_tone import strip_sandbox_links
from thomas.agent.routing import IntentRouter
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class DummyLLM:
    def __init__(self, text: str = "hi") -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)
        self.text = text
        self.last_messages: list[dict[str, Any]] = []
        self.last_tools: list[dict[str, Any]] = []

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self.last_messages = list(messages or [])
        self.last_tools = list(tools or [])
        yield StreamEvent(type="token", data={"text": self.text})
        yield StreamEvent(type="done", data={})


class DummyTool(Tool):
    name = "dummy.echo"
    category = "test"
    description = "Echo structured model input."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"args": args})


def make_agent(*, text: str = "hi", conversation: list[dict[str, Any]] | None = None):
    config = AppConfig(models={"frontier": ModelConfig(name="frontier", model="gpt-5.6-sol")}, default_model="frontier")
    tools = ToolRegistry()
    tools.register(DummyTool())
    llm = DummyLLM(text)
    history = [] if conversation is None else conversation
    return AgentLoop(config, llm, tools, conversation=history), llm, history


class TestAgentLoopConversation(unittest.TestCase):
    def test_structured_route_prompt_selects_template_without_reading_user_prose(self) -> None:
        low = build_route_system_prompt(
            route_path="casual_chat",
            cwd="F:\\Thomas",
            platform="win32",
            model_name="frontier",
            model_id="gpt-5.6-sol",
        )
        coding = build_route_system_prompt(
            route_path="coding_task",
            cwd="F:\\Thomas",
            platform="win32",
            model_name="frontier",
            model_id="gpt-5.6-sol",
        )
        self.assertIn('route="low_intent"', low)
        self.assertIn('route="execution"', coding)

    def test_natural_language_topics_share_one_model_owned_route(self) -> None:
        router = IntentRouter()
        prompts = [
            "hello",
            "make me a graph",
            "build a game",
            "fix app.py",
            "make a PDF",
            "continue",
        ]
        decisions = [router.decide(prompt) for prompt in prompts]
        self.assertEqual({decision.path for decision in decisions}, {"model_owned"})
        self.assertEqual({tuple(decision.reasons) for decision in decisions}, {("model_owned",)})

    def test_current_turn_is_not_rewritten_or_augmented_by_prompt_classifier(self) -> None:
        history = [{"role": "assistant", "content": "Reply ok and I will build a game."}]
        agent, llm, _ = make_agent(conversation=history)

        async def run_once():
            return [event async for event in agent.run("make a graph", tools_policy="auto")]

        events = asyncio.run(run_once())
        start = next(event for event in events if event.type == EventType.AGENT_START)
        self.assertEqual(start.data.get("route_input_source"), "current_turn")
        self.assertEqual(start.data.get("prompt"), "make a graph")
        user_messages = [message.get("content") for message in llm.last_messages if message.get("role") == "user"]
        self.assertEqual(user_messages[-1], "make a graph")

    def test_conversation_list_is_preserved_without_duplicate_turns(self) -> None:
        agent, _llm, history = make_agent()

        async def run_once():
            async for _ in agent.run("hello", tools_policy="never"):
                pass

        asyncio.run(run_once())
        self.assertEqual([message.get("role") for message in history], ["user", "assistant"])
        self.assertEqual(history[0].get("content"), "hello")
        self.assertEqual(history[1].get("content"), "hi")

    def test_auto_policy_exposes_capabilities_for_every_topic(self) -> None:
        for prompt in ("how are you", "make a graph", "fix app.py"):
            agent, llm, _ = make_agent()

            async def run_once():
                async for _ in agent.run(prompt, tools_policy="auto"):
                    pass

            asyncio.run(run_once())
            names = {
                str(spec.get("name") or (spec.get("function") or {}).get("name") or "")
                for spec in llm.last_tools
            }
            self.assertEqual(names, {"dummy.echo"})

    def test_model_prose_is_preserved_verbatim(self) -> None:
        prose = "Certainly. Here is a game-shaped answer even though you asked for a graph. What next?"
        agent, _llm, _ = make_agent(text=prose)
        route = IntentRouter().decide("make a graph")
        out, changed = agent._sanitize_assistant_text(
            prose,
            prompt_text="make a graph",
            route=route,
            route_input_source="current_turn",
            pending_tool_calls=0,
        )
        self.assertFalse(changed)
        self.assertEqual(out, prose)

    def test_only_browser_inaccessible_local_link_target_is_removed(self) -> None:
        prose = "Done: [graph](sandbox:/mnt/data/graph.pdf). Keep this exact sentence."
        self.assertEqual(strip_sandbox_links(prose), "Done: graph. Keep this exact sentence.")

    def test_multimodal_prompt_is_forwarded_to_frontier_model(self) -> None:
        agent, llm, _ = make_agent(text="ok")
        prompt = [
            {"type": "text", "text": "describe this image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]

        async def run_once():
            return [event async for event in agent.run(prompt)]

        events = asyncio.run(run_once())
        self.assertEqual(len([event for event in events if event.type == EventType.AGENT_DONE]), 1)
        user_message = next(message for message in llm.last_messages if message.get("role") == "user")
        self.assertEqual(user_message.get("content"), prompt)


if __name__ == "__main__":
    unittest.main()
