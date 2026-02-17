import asyncio
import unittest

from thomas.agent.loop import AgentLoop
from thomas.agent.routing import IntentRouter
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class DummyLLM:
    def __init__(self) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        yield StreamEvent(type="token", data={"text": "hi"})
        yield StreamEvent(type="done", data={})


class DummyLLMText:
    def __init__(self, text: str) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)
        self._text = str(text)

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        yield StreamEvent(type="token", data={"text": self._text})
        yield StreamEvent(type="done", data={})


class DummyTool(Tool):
    name = "dummy.echo"
    category = "test"
    description = "echo"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"ok": True})


class TestAgentLoopConversation(unittest.TestCase):
    def test_conversation_list_is_preserved_when_empty(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        conversation = []
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=conversation)
        self.assertIs(agent._conversation, conversation)  # intentional: internal contract

    def test_single_turn_no_duplication(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        conversation = []
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=conversation)

        async def run_once():
            async for _ in agent.run("hello", tools_policy="never"):
                pass

        asyncio.run(run_once())

        self.assertEqual([m.get("role") for m in conversation], ["user", "assistant"])
        self.assertEqual(conversation[0].get("content"), "hello")
        self.assertEqual(conversation[1].get("content"), "hi")

    def test_input_continuity_hint_accepts_token_reply(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        conversation = [
            {"role": "assistant", "content": "Send your Telegram bot token and chat id so I can continue setup."}
        ]
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=conversation)
        hint = agent._input_continuity_hint("123456789:ABCdef_1234567890-zzYYxx")
        self.assertIn("Telegram bot token", hint)

    def test_agent_start_emits_history_policy(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        conversation = []
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=conversation)

        async def run_once():
            events = []
            async for ev in agent.run("are you working", tools_policy="auto"):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        start = next((e for e in events if e.type == EventType.AGENT_START), None)
        self.assertIsNotNone(start)
        assert start is not None
        policy = start.data.get("history_policy")
        self.assertIsInstance(policy, dict)
        self.assertGreaterEqual(int(policy.get("preserve_last", 0) or 0), 10)

    def test_history_preserve_counts_for_coding_and_casual(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        router = IntentRouter()

        casual = router.decide("hey you there?")
        coding = router.decide("set up telegram integration for me")

        c_first, c_last = agent._history_preserve_counts(casual)
        k_first, k_last = agent._history_preserve_counts(coding)

        self.assertEqual(c_first, 0)
        self.assertGreaterEqual(c_last, 10)
        self.assertEqual(k_first, 0)
        self.assertLessEqual(k_last, 10)

    def test_routing_input_uses_previous_assistant_for_ack_followup(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        conversation = [
            {
                "role": "assistant",
                "content": "I can set up Telegram integration now. Reply ok and I will continue.",
            }
        ]
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=conversation)
        routed, src = agent._routing_input_text("ok")
        self.assertEqual(src, "history_augmented")
        self.assertIn("Telegram integration", routed)
        self.assertIn("User reply: ok", routed)

    def test_ack_followup_routes_as_coding_from_previous_context(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        tools.register(DummyTool())
        conversation = [
            {
                "role": "assistant",
                "content": "I can set up Telegram integration and run the install now. Reply ok to proceed.",
            }
        ]
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=conversation)

        async def run_once():
            events = []
            async for ev in agent.run("ok", tools_policy="auto"):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        start = next((e for e in events if e.type == EventType.AGENT_START), None)
        self.assertIsNotNone(start)
        assert start is not None
        route = start.data.get("route") or {}
        self.assertEqual(route.get("path"), "coding_task")
        self.assertEqual(start.data.get("route_input_source"), "history_augmented")

    def test_select_tools_respects_route_even_for_short_prompt(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        tools.register(DummyTool())
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        route = IntentRouter().decide("set up telegram integration for me")
        specs = agent._select_tools("ok", policy="auto", route=route)
        self.assertIsInstance(specs, list)
        assert specs is not None
        self.assertGreaterEqual(len(specs), 1)

    def test_sanitize_removes_premature_what_next_on_continuation(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        conversation = [
            {
                "role": "assistant",
                "content": "I can continue Telegram setup now. Reply ok to proceed.",
            }
        ]
        agent = AgentLoop(
            cfg,
            DummyLLMText("Great, continuing now. What would you like me to do next?"),
            tools,
            conversation=conversation,
        )

        async def run_once():
            events = []
            async for ev in agent.run("ok", tools_policy="auto"):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
        self.assertIsNotNone(done)
        assert done is not None
        txt = str(done.data.get("text") or "")
        self.assertNotIn("What would you like me to do next?", txt)
        cont = (done.data.get("token_report") or {}).get("continuity") or {}
        self.assertGreaterEqual(int(cont.get("followup_suppressed_count", 0) or 0), 1)

    def test_sanitize_keeps_question_when_blocked_for_missing_input(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        conversation = [
            {
                "role": "assistant",
                "content": "Send your Telegram token and chat id so I can finish setup.",
            }
        ]
        agent = AgentLoop(
            cfg,
            DummyLLMText("I still need your Telegram token. What is it?"),
            tools,
            conversation=conversation,
        )

        async def run_once():
            events = []
            async for ev in agent.run("ok", tools_policy="auto"):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
        self.assertIsNotNone(done)
        assert done is not None
        txt = str(done.data.get("text") or "")
        self.assertIn("What is it?", txt)
