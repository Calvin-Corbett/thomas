import asyncio
import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from thomas.agent.loop import AgentLoop
from thomas.agent.loop_streaming import apply_memory_policy, validate_memory_relevance
from thomas.agent.routing import RouteDecision
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent, TokenUsage
from thomas.core.token_economy import normalize_token_economy_level, runtime_overhead_policy
from thomas.tools.registry import ToolRegistry


@dataclass
class _Ctx:
    text: str


class DummyMemory:
    def __init__(self) -> None:
        self.started = True
        self.retrieve_calls: list[dict[str, Any]] = []
        self.events: list[dict[str, str]] = []
        self.pins: dict[str, str] = {}
        self.ingest_calls = 0
        self.thread_policies: dict[str, dict[str, Any]] = {}

    def retrieve(self, query: str, thread: str, budget: int, mode: str) -> _Ctx:  # noqa: D401
        self.retrieve_calls.append({"query": query, "thread": thread, "budget": budget, "mode": mode})
        return _Ctx(text="remembered context")

    def add_event(self, thread: str, etype: str, text: str) -> int:
        self.events.append({"thread": thread, "etype": etype, "text": text})
        return len(self.events)

    def pin(self, key: str, text: str) -> None:
        self.pins[key] = text

    def ingest_pending(self) -> dict[str, int]:
        self.ingest_calls += 1
        return {"indexed": 0}

    def set_thread_memory_policy(self, thread_id: str, **patch: Any) -> dict[str, Any]:
        current = dict(self.thread_policies.get(thread_id, {}))
        current.update(patch)
        self.thread_policies[thread_id] = current
        return current

    def thread_memory_policy(self, thread_id: str) -> dict[str, Any]:
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

    def test_memory_retrieval_runs_for_actionable_prompt(self) -> None:
        agent, memory = self._build_agent()

        async def run_once():
            async for _ in agent.run("find the bug in main.py", tools_policy="never", mode="auto"):
                pass
            await asyncio.sleep(0.02)

        asyncio.run(run_once())

        self.assertGreaterEqual(len(memory.retrieve_calls), 1)
        self.assertEqual(memory.retrieve_calls[0]["mode"], "auto")

    def test_fast_mode_uses_fast_memory_retrieval(self) -> None:
        agent, memory = self._build_agent()

        async def run_once():
            async for _ in agent.run("inspect server.py and fix the bug", tools_policy="never", mode="fast"):
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
        self.assertTrue(policy.get("include_global"))
        self.assertFalse(policy.get("include_profile"))

    def test_memory_policy_pref_overrides_apply_to_thread_settings(self) -> None:
        agent, memory = self._build_agent()
        agent._memory_include_thread_pref = False
        agent._memory_include_global_pref = True
        agent._memory_include_profile_pref = False
        agent._memory_pins_only_pref = True
        agent._memory_max_pack_tokens_pref = 1400
        agent._memory_max_results_pref = 3
        agent._memory_decay_half_life_hours_pref = 6.0
        agent._memory_auto_compact_enabled_pref = False
        agent._memory_auto_compact_episode_threshold_pref = 12
        agent._memory_auto_compact_min_interval_hours_pref = 0.5
        agent._memory_auto_optimize_enabled_pref = True
        agent._memory_auto_optimize_waste_threshold_pref = 0.33
        agent._memory_auto_optimize_min_interval_hours_pref = 1.25

        route = RouteDecision(
            path="general",
            confidence=1.0,
            reasons=["test"],
            mode="auto",
            tools_policy="auto",
            include_purpose=False,
            memory_include_global=False,
            memory_include_profile=True,
            memory_budget_tokens=800,
        )
        apply_memory_policy(agent, route)

        policy = memory.thread_memory_policy("t1")
        self.assertTrue(policy.get("enabled"))
        self.assertFalse(policy.get("include_thread"))
        self.assertTrue(policy.get("include_global"))
        self.assertFalse(policy.get("include_profile"))
        self.assertTrue(policy.get("pins_only"))
        self.assertEqual(int(policy.get("max_pack_tokens") or 0), 1400)
        self.assertEqual(int(policy.get("max_results") or 0), 3)
        self.assertAlmostEqual(float(policy.get("decay_half_life_hours") or 0.0), 6.0, places=6)
        self.assertFalse(bool(policy.get("auto_compact_enabled")))
        self.assertEqual(int(policy.get("auto_compact_episode_threshold") or 0), 12)
        self.assertAlmostEqual(float(policy.get("auto_compact_min_interval_hours") or 0.0), 0.5, places=6)
        self.assertTrue(bool(policy.get("auto_optimize_enabled")))
        self.assertAlmostEqual(float(policy.get("auto_optimize_waste_threshold") or 0.0), 0.33, places=6)
        self.assertAlmostEqual(float(policy.get("auto_optimize_min_interval_hours") or 0.0), 1.25, places=6)

    def test_memory_policy_respects_token_economy_profile_cap(self) -> None:
        agent, memory = self._build_agent()
        agent._memory_include_profile_economy_cap = False

        route = RouteDecision(
            path="general",
            confidence=1.0,
            reasons=["test"],
            mode="auto",
            tools_policy="auto",
            include_purpose=False,
            memory_include_global=True,
            memory_include_profile=True,
            memory_budget_tokens=800,
        )
        apply_memory_policy(agent, route)

        policy = memory.thread_memory_policy("t1")
        self.assertFalse(policy.get("include_profile"))

    def test_runtime_overhead_policy_balances_prompt_extras(self) -> None:
        self.assertEqual(normalize_token_economy_level("balanced"), "optimal")

        cheap = runtime_overhead_policy("cheap")
        optimal = runtime_overhead_policy("balanced")
        max_policy = runtime_overhead_policy("max")

        self.assertFalse(cheap.include_autonomy_profile)
        self.assertFalse(cheap.include_library_context)
        self.assertEqual(cheap.runtime_skills_mode, "off")

        self.assertTrue(optimal.include_autonomy_profile)
        self.assertTrue(optimal.include_project_instructions)
        self.assertFalse(optimal.include_memory_profile)
        self.assertEqual(optimal.runtime_skills_mode, "explicit")

        self.assertTrue(max_policy.include_memory_profile)
        self.assertTrue(max_policy.include_test_visibility_hint)
        self.assertEqual(max_policy.runtime_skills_mode, "auto")

    def test_build_system_message_can_omit_optional_overhead_sections(self) -> None:
        agent, _memory = self._build_agent()
        with (
            patch("thomas.agent.loop_core._load_purpose_text", return_value="purpose text"),
            patch("thomas.agent.loop_core.discover_project_instructions", return_value="project instructions"),
            patch("thomas.agent.loop_core.format_project_instructions", return_value="--- Project Instructions ---"),
        ):
            disabled = agent._build_system_message(
                "",
                include_purpose=False,
                route_path="coding_task",
                skills_context="",
                include_autonomy_profile=False,
                include_editing_policy=False,
                include_project_instructions=False,
            )
            enabled = agent._build_system_message(
                "",
                include_purpose=True,
                route_path="coding_task",
                skills_context="SKILLS",
                include_autonomy_profile=True,
                include_editing_policy=True,
                include_project_instructions=True,
            )

        disabled_text = str(disabled.get("content") or "")
        enabled_text = str(enabled.get("content") or "")
        self.assertNotIn("Autonomy Profile", disabled_text)
        self.assertNotIn("Editing Policy", disabled_text)
        self.assertNotIn("Purpose Brief", disabled_text)
        self.assertNotIn("Project Instructions", disabled_text)

        self.assertIn("Autonomy Profile", enabled_text)
        self.assertIn("Editing Policy", enabled_text)
        self.assertIn("Purpose Brief", enabled_text)
        self.assertIn("Project Instructions", enabled_text)
        self.assertIn("SKILLS", enabled_text)

    def test_validate_memory_relevance_prefers_query_term_coverage(self) -> None:
        strong = validate_memory_relevance(
            "deployment target cloudflare workers",
            "Durable memory: deployment target is Cloudflare Workers.",
        )
        weak = validate_memory_relevance(
            "deployment target cloudflare workers",
            "Durable memory: favorite pizza toppings are mushrooms and olives.",
        )

        self.assertGreater(strong, 0.5)
        self.assertEqual(weak, 0.0)

    def test_agent_loop_generates_unique_fallback_ids_when_not_provided(self) -> None:
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
        )
        tools = ToolRegistry()

        first = AgentLoop(cfg, DummyLLM(), tools, conversation=[], memory=DummyMemory())
        second = AgentLoop(cfg, DummyLLM(), tools, conversation=[], memory=DummyMemory())

        self.assertTrue(first._thread_id.startswith("thread:"))
        self.assertTrue(second._thread_id.startswith("thread:"))
        self.assertNotEqual(first._thread_id, second._thread_id)
        self.assertEqual(first._session_id, first._thread_id)
        self.assertEqual(second._session_id, second._thread_id)
        self.assertTrue(first._run_id.startswith("run:"))
        self.assertTrue(second._run_id.startswith("run:"))
        self.assertNotEqual(first._run_id, second._run_id)

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
        self.assertEqual(int(report1.get("total_tokens", 0)), 300)

        # Session usage grows across turns, but per-run reporting must not.
        self.assertEqual(int(llm.session_usage.total_tokens), 600)
        self.assertEqual(int(usage2.get("prompt_tokens", 0)), 220)
        self.assertEqual(int(usage2.get("completion_tokens", 0)), 80)
        self.assertEqual(int(usage2.get("total_tokens", 0)), 300)
        self.assertEqual(int(report2.get("total_tokens", 0)), 300)
