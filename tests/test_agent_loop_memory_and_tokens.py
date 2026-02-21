import asyncio
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent, TokenUsage
from thomas.tools.registry import ToolRegistry


@dataclass
class _Ctx:
    text: str


class DummyMemory:
    def __init__(self) -> None:
        self.started = True
        self.retrieve_calls: List[Dict[str, Any]] = []
        self.events: List[Dict[str, str]] = []
        self.pins: Dict[str, str] = {}
        self.ingest_calls = 0
        self.thread_policies: Dict[str, Dict[str, Any]] = {}

    def retrieve(self, query: str, thread: str, budget: int, mode: str) -> _Ctx:  # noqa: D401
        self.retrieve_calls.append(
            {"query": query, "thread": thread, "budget": budget, "mode": mode}
        )
        return _Ctx(text="remembered context")

    def add_event(self, thread: str, etype: str, text: str) -> int:
        self.events.append({"thread": thread, "etype": etype, "text": text})
        return len(self.events)

    def pin(self, key: str, text: str) -> None:
        self.pins[key] = text

    def ingest_pending(self) -> Dict[str, int]:
        self.ingest_calls += 1
        return {"indexed": 0}

    def set_thread_memory_policy(self, thread_id: str, **patch: Any) -> Dict[str, Any]:
        current = dict(self.thread_policies.get(thread_id, {}))
        current.update(patch)
        self.thread_policies[thread_id] = current
        return current

    def thread_memory_policy(self, thread_id: str) -> Dict[str, Any]:
        return dict(self.thread_policies.get(thread_id, {}))


class DummyLLM:
    def __init__(self, prompt_tokens: int = 1500, completion_tokens: int = 300) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=128)
        self._prompt_tokens = int(prompt_tokens)
        self._completion_tokens = int(completion_tokens)
        self.session_usage = TokenUsage()

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        usage = TokenUsage(
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            total_tokens=self._prompt_tokens + self._completion_tokens,
        )
        self.session_usage.add(usage)
        yield StreamEvent(type="token", data={"text": "ok"})
        yield StreamEvent(type="done", data={})


class TestAgentLoopMemoryAndTokens(unittest.TestCase):
    def _build_agent(self) -> tuple[AgentLoop, DummyMemory]:
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
        )
        tools = ToolRegistry()
        memory = DummyMemory()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[], memory=memory, thread_id="t1")
        return agent, memory

    def test_memory_retrieval_is_always_on_for_general_chat(self) -> None:
        agent, memory = self._build_agent()

        async def run_once():
            async for _ in agent.run("hello how are you", tools_policy="never", mode="auto"):
                pass
            await asyncio.sleep(0.02)

        asyncio.run(run_once())

        self.assertGreaterEqual(len(memory.retrieve_calls), 1)
        self.assertEqual(memory.retrieve_calls[0]["mode"], "auto")

    def test_fast_mode_uses_fast_memory_retrieval(self) -> None:
        agent, memory = self._build_agent()

        async def run_once():
            async for _ in agent.run("just a quick answer", tools_policy="never", mode="fast"):
                pass
            await asyncio.sleep(0.02)

        asyncio.run(run_once())

        self.assertGreaterEqual(len(memory.retrieve_calls), 1)
        self.assertEqual(memory.retrieve_calls[0]["mode"], "fast")

    def test_done_event_includes_usage_and_token_report(self) -> None:
        agent, memory = self._build_agent()

        async def run_once():
            events = []
            async for ev in agent.run("my name is Alex and I prefer concise replies.", tools_policy="never"):
                events.append(ev)
            await asyncio.sleep(0.02)
            return events

        events = asyncio.run(run_once())
        done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
        self.assertIsNotNone(done)
        assert done is not None

        usage = done.data.get("usage")
        token_report = done.data.get("token_report")
        self.assertIsInstance(usage, dict)
        self.assertIsInstance(token_report, dict)
        self.assertEqual(usage.get("prompt_tokens"), 1500)
        self.assertIn("prompt_to_completion_ratio", token_report)
        self.assertIn("suggestions", token_report)
        self.assertIn("route", token_report)
        # Profile hints should be promoted to pins.
        self.assertIn("user.name", memory.pins)
        self.assertIn("user.preference", memory.pins)

    def test_route_applies_thread_memory_policy_for_casual_chat(self) -> None:
        agent, memory = self._build_agent()

        async def run_once():
            async for _ in agent.run("hello", tools_policy="auto"):
                pass
            await asyncio.sleep(0.02)

        asyncio.run(run_once())

        policy = memory.thread_memory_policy("t1")
        self.assertTrue(policy.get("enabled"))
        self.assertFalse(policy.get("include_global"))
        self.assertTrue(policy.get("include_profile"))

    def test_usage_is_scoped_to_single_run_not_session_cumulative(self) -> None:
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
        )
        tools = ToolRegistry()
        memory = DummyMemory()
        llm = DummyLLM(prompt_tokens=220, completion_tokens=80)
        agent = AgentLoop(cfg, llm, tools, conversation=[], memory=memory, thread_id="t1")

        async def run_once(prompt: str):
            events = []
            async for ev in agent.run(prompt, tools_policy="never", mode="auto"):
                events.append(ev)
            await asyncio.sleep(0.02)
            done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
            self.assertIsNotNone(done)
            assert done is not None
            return done.data.get("usage") or {}, done.data.get("token_report") or {}

        usage1, report1 = asyncio.run(run_once("first turn"))
        usage2, report2 = asyncio.run(run_once("second turn"))

        self.assertEqual(int(usage1.get("prompt_tokens", 0)), 220)
        self.assertEqual(int(usage1.get("completion_tokens", 0)), 80)
        self.assertEqual(int(usage1.get("total_tokens", 0)), 300)

        # Session usage grows across turns, but per-run reporting must not.
        self.assertEqual(int(llm.session_usage.total_tokens), 600)
        self.assertEqual(int(usage2.get("prompt_tokens", 0)), 220)
        self.assertEqual(int(usage2.get("completion_tokens", 0)), 80)
        self.assertEqual(int(usage2.get("total_tokens", 0)), 300)
        self.assertEqual(int(report2.get("total_tokens", 0)), 300)
