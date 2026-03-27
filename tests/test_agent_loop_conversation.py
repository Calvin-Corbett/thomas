import asyncio
import unittest

from thomas.agent.loop import AgentLoop
from thomas.agent.prompt_templates import build_route_system_prompt
from thomas.agent.response_tone import (
    best_practice_gate_hint,
    live_test_default_hint,
    prompt_requests_best_practice_gate,
    prompt_requests_directness_constraints,
)
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


class DummyLLMTextSequence:
    def __init__(self, texts):  # noqa: ANN001
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)
        self._texts = [str(x) for x in (texts or [])]
        self._idx = 0

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = messages
        _ = tools
        if not self._texts:
            text = ""
        elif self._idx < len(self._texts):
            text = self._texts[self._idx]
        else:
            text = self._texts[-1]
        self._idx += 1
        yield StreamEvent(type="token", data={"text": text})
        yield StreamEvent(type="done", data={})


class CaptureLLM:
    def __init__(self, text: str = "ok") -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)
        self._text = str(text)
        self.last_messages = []
        self.last_tools = []

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self.last_messages = list(messages or [])
        self.last_tools = list(tools or [])
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
    def test_build_route_system_prompt_uses_low_intent_template(self) -> None:
        prompt = build_route_system_prompt(
            route_path="casual_chat",
            cwd="F:\\DevHub\\Thomas",
            platform="win32",
            model_name="local",
            model_id="qwen",
        )
        self.assertIn('route="low_intent"', prompt)
        self.assertIn("natural and practical assistant", prompt)
        self.assertIn("Do not output pseudo tool-call text", prompt)
        self.assertIn("<runtime_context>", prompt)

    def test_build_route_system_prompt_uses_full_template_for_coding(self) -> None:
        prompt = build_route_system_prompt(
            route_path="coding_task",
            cwd="F:\\DevHub\\Thomas",
            platform="win32",
            model_name="local",
            model_id="qwen",
        )
        self.assertIn('route="execution"', prompt)
        self.assertIn("practical execution assistant", prompt)
        self.assertIn("<execution_contract>", prompt)

    def test_prompt_requests_directness_constraints_detects_one_sentence(self) -> None:
        self.assertTrue(prompt_requests_directness_constraints("that's not what i asked. try again in one sentence."))

    def test_prompt_requests_best_practice_gate_detects_non_coder_request(self) -> None:
        self.assertTrue(
            prompt_requests_best_practice_gate("idk how to code. always use the best practice robust method.")
        )

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

    def test_routing_input_prefers_original_request_from_control_envelope(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        prompt = (
            "Continue execution now. "
            "(clarification_retry=1; clarification_cap=0; clarification_seen=1; "
            "route_input_source=prompt_only; original_request=fix the chat route fallback)"
        )
        routed, src = agent._routing_input_text(prompt)
        self.assertEqual(src, "prompt_only")
        self.assertEqual(routed, "fix the chat route fallback")

    def test_assume_nudge_reuses_original_request_when_prompt_already_wrapped(self) -> None:
        wrapped_prompt = (
            "Continue execution now. "
            "(clarification_retry=1; clarification_cap=0; clarification_seen=1; "
            "route_input_source=prompt_only; original_request=ship the memory toggle fix)"
        )
        nudge = AgentLoop._assume_and_proceed_nudge(
            wrapped_prompt,
            retry_index=2,
            question_cap=0,
            questions_seen=2,
            route_input_source="prompt_only",
        )
        self.assertIn("original_request=ship the memory toggle fix", nudge)

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

    def test_reply_first_casual_turn_omits_tool_specs_from_llm_call(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        tools.register(DummyTool())
        llm = CaptureLLM("hello")
        agent = AgentLoop(cfg, llm, tools, conversation=[])

        async def run_once():
            async for _ in agent.run("hey there", tools_policy="auto"):
                pass

        asyncio.run(run_once())
        self.assertEqual(llm.last_tools, [])

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

    def test_clarification_budget_reprompts_on_history_augmented_full_auto(self) -> None:
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
            DummyLLMTextSequence(
                [
                    "Which branch should I use?",
                    "Proceeding with default branch and finishing setup now.",
                ]
            ),
            tools,
            conversation=conversation,
            autonomy_level=4,
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
        self.assertIn("finishing setup now", str(done.data.get("text") or "").lower())
        continuity = (done.data.get("token_report") or {}).get("continuity") or {}
        self.assertEqual(int(continuity.get("clarification_question_cap", -1)), 0)
        self.assertGreaterEqual(int(continuity.get("clarification_questions_asked", 0) or 0), 1)
        self.assertGreaterEqual(int(continuity.get("clarification_reprompt_count", 0) or 0), 1)
        self.assertGreaterEqual(int(continuity.get("full_auto_reprompt_count", 0) or 0), 1)

    def test_clarification_budget_does_not_suppress_credential_request(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        conversation = [
            {
                "role": "assistant",
                "content": "I can continue setup now. Reply ok to proceed.",
            }
        ]
        agent = AgentLoop(
            cfg,
            DummyLLMTextSequence(["I need your API key. What is it?"]),
            tools,
            conversation=conversation,
            autonomy_level=4,
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
        self.assertIn("What is it?", str(done.data.get("text") or ""))
        continuity = (done.data.get("token_report") or {}).get("continuity") or {}
        self.assertEqual(int(continuity.get("clarification_reprompt_count", 0) or 0), 0)

    def test_sanitize_on_frustration_strips_robotic_opener_without_stock_prefix(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "Understood. I will update the behavior tuning and run live tests now.",
            prompt_text="You sound robotic and this is frustrating.",
            route=IntentRouter().decide("You sound robotic and this is frustrating."),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertFalse(out.startswith("You're right to call that out."))
        self.assertNotIn("Understood.", out)

    def test_sanitize_strips_generic_followup_on_frustration_feedback(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "Sure. I'll keep the tone natural. How can I assist you further?",
            prompt_text="you are too robotic",
            route=IntentRouter().decide("you are too robotic"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertNotIn("How can I assist you further?", out)
        self.assertIn("tone natural", out)

    def test_sanitize_removes_trailing_robotic_fillers(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "You're right to call that out. Understood.",
            prompt_text="you are too robotic",
            route=IntentRouter().decide("you are too robotic"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertNotIn("Understood.", out)
        self.assertIn("You're right to call that out.", out)

    def test_sanitize_strips_unprompted_workspace_path_for_casual_turns(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "Hi. What do you want to work on in `F:\\DevHub\\Thomas`?",
            prompt_text="hi",
            route=IntentRouter().decide("hi"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertEqual(out, "Hi. What do you want to work on?")

    def test_sanitize_strips_thinking_out_loud_prefix(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "Let me think this through. The fix is to hydrate preferences on startup.",
            prompt_text="why does onboarding keep showing?",
            route=IntentRouter().decide("why does onboarding keep showing?"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertNotIn("Let me think", out)
        self.assertIn("The fix is to hydrate preferences on startup.", out)

    def test_sanitize_strips_reasoning_tags_and_meta_phrases(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "<thinking>I should reason this out before replying.</thinking>\n"
            "Here is my thought process: patch the route and rerun tests.",
            prompt_text="you explain too much",
            route=IntentRouter().decide("you explain too much"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertNotIn("<thinking>", out)
        self.assertNotIn("thought process", out.lower())
        self.assertIn("patch the route and rerun tests", out.lower())

    def test_sanitize_keeps_blocked_question_but_drops_thinking_prefix(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "Let me think. I still need your Telegram token. What is it?",
            prompt_text="ok",
            route=IntentRouter().decide("ok"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertNotIn("Let me think", out)
        self.assertIn("What is it?", out)

    def test_sanitize_collapses_reasoning_scaffold_to_final_answer(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "Sure, let's break down the problem step by step:\n\n"
            "1. **Understanding the Question**: Add 2 and 2.\n"
            "2. **Basic Arithmetic**: 2 + 2 = 4.\n"
            "Therefore, the answer is 4.",
            prompt_text="Think out loud and explain your thought process before answering: what is 2+2?",
            route=IntentRouter().decide(
                "Think out loud and explain your thought process before answering: what is 2+2?"
            ),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertNotIn("step by step", out.lower())
        self.assertNotIn("1.", out)
        self.assertIn("answer is 4", out.lower())

    def test_sanitize_strips_tool_call_json_artifacts(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "List Configuration Files:\n\njson\nCopy\n"
            '{"name": "fs_list_dir", "arguments": {"path": "**/*.json"}}\n\n'
            "After running these commands, review the results.",
            prompt_text="my settings keep resetting every restart. where should i look first?",
            route=IntentRouter().decide("my settings keep resetting every restart. where should i look first?"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertNotIn('"name": "fs_list_dir"', out)
        self.assertNotIn("\njson\n", out.lower())
        self.assertIn("After running these commands", out)

    def test_sanitize_honors_one_sentence_request(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "Close your eyes for 5 minutes and take deep breaths. When you're ready, we can tackle something specific.",
            prompt_text="that's not what i asked. try again in one sentence.",
            route=IntentRouter().decide("that's not what i asked. try again in one sentence."),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertEqual(out, "Close your eyes for 5 minutes and take deep breaths.")

    def test_sanitize_strips_pseudo_tool_blocks(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "You can start by running:\n\nsh\nCopy\nshell.exec(\"find . -name '*.json'\")\n\n"
            'Then inspect files with:\n\nsh\nCopy\nfs.read_file("path/to/file.json")\n\n'
            "Review the file values after that.",
            prompt_text="my settings keep resetting every restart. where should i look first?",
            route=IntentRouter().decide("my settings keep resetting every restart. where should i look first?"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertNotIn("shell.exec(", out)
        self.assertNotIn("fs.read_file(", out)
        self.assertIn("Review the file values", out)

    def test_sanitize_strips_pseudo_tool_arg_lines(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "Run this first:\n\nsh\nCopy\n"
            'fs.list_dir path="F:\\\\DevHub\\\\Thomas" pattern="*.json,*.yaml"\n\n'
            "Then read files after listing.",
            prompt_text="my settings keep resetting every restart. where should i look first?",
            route=IntentRouter().decide("my settings keep resetting every restart. where should i look first?"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertNotIn("fs.list_dir path=", out)
        self.assertIn("Then read files", out)

    def test_sanitize_one_thing_prompt_drops_trailing_question(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "Close your eyes for 5 minutes and take deep breaths. What do you think?",
            prompt_text="give me one thing i can do in the next 10 minutes.",
            route=IntentRouter().decide("give me one thing i can do in the next 10 minutes."),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertNotIn("What do you think?", out)
        self.assertIn("Close your eyes", out)

    def test_sanitize_where_first_prefers_single_prioritized_step(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "To troubleshoot why your settings are resetting every time you restart, you should start by checking the following:\n\n"
            "Configuration Files: Look for config files that save/load settings.\n\n"
            "Environment Variables: Check env vars that might override settings.\n\n"
            "Application Logs: Review errors around persistence.",
            prompt_text="my settings keep resetting every restart where should i look first",
            route=IntentRouter().decide("my settings keep resetting every restart where should i look first"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertTrue(changed)
        self.assertEqual(out, "Configuration Files: Look for config files that save/load settings.")

    def test_sanitize_keeps_workspace_path_when_user_asks_location(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(cfg, DummyLLM(), tools, conversation=[])
        out, changed = agent._sanitize_assistant_text(
            "You are currently in `F:\\DevHub\\Thomas`.",
            prompt_text="what folder are you in",
            route=IntentRouter().decide("what folder are you in"),
            route_input_source="prompt_only",
            pending_tool_calls=0,
        )
        self.assertFalse(changed)
        self.assertIn("F:\\DevHub\\Thomas", out)

    def test_thought_leak_metric_recorded_in_token_report(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(
            cfg,
            DummyLLMText("Let me think out loud. The issue is stale onboarding state."),
            tools,
            conversation=[],
        )

        async def run_once():
            events = []
            async for ev in agent.run("why does onboarding repeat?", tools_policy="never"):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
        self.assertIsNotNone(done)
        assert done is not None
        continuity = (done.data.get("token_report") or {}).get("continuity") or {}
        self.assertGreaterEqual(int(continuity.get("thought_leak_suppressed_count", 0) or 0), 1)

    def test_low_intent_text_delta_is_sanitized_before_emit(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(
            cfg,
            DummyLLMText("Let me think this through. The answer is 4."),
            tools,
            conversation=[],
        )

        async def run_once():
            events = []
            async for ev in agent.run("what is 2+2?"):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        streamed = "".join(str(e.data.get("text") or "") for e in events if e.type == EventType.TEXT_DELTA)
        self.assertNotIn("Let me think", streamed)
        self.assertIn("The answer is 4.", streamed)

    def test_action_route_text_delta_is_sanitized_before_emit(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(
            cfg,
            DummyLLMText(
                "Let me think this through. Here's my thought process: "
                "Start with parser.py because config defaults are likely not persisted."
            ),
            tools,
            conversation=[],
        )

        async def run_once():
            events = []
            async for ev in agent.run("please debug why settings reset after restart"):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        streamed = "".join(str(e.data.get("text") or "") for e in events if e.type == EventType.TEXT_DELTA)
        self.assertNotIn("Let me think", streamed)
        self.assertNotIn("thought process", streamed.lower())
        self.assertIn("Start with parser.py", streamed)

    def test_directness_prompt_text_delta_is_sanitized_before_emit(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        agent = AgentLoop(
            cfg,
            DummyLLMText(
                "How about setting a small, achievable task for the next 10 minutes? "
                "For example, write down three things you need to do today."
            ),
            tools,
            conversation=[],
        )

        async def run_once():
            events = []
            async for ev in agent.run("that's not what i asked. try again in one sentence."):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        streamed = "".join(str(e.data.get("text") or "") for e in events if e.type == EventType.TEXT_DELTA)
        self.assertIn("How about setting a small, achievable task", streamed)
        self.assertNotIn("For example, write down three things", streamed)

    def test_multimodal_prompt_is_forwarded_to_llm(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        llm = CaptureLLM("ok")
        agent = AgentLoop(cfg, llm, tools, conversation=[])
        prompt = [
            {"type": "text", "text": "describe this image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]

        async def run_once():
            events = []
            async for ev in agent.run(prompt):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        self.assertEqual(len([e for e in events if e.type == EventType.AGENT_DONE]), 1)
        user_msg = next((m for m in llm.last_messages if m.get("role") == "user"), {})
        content = user_msg.get("content")
        self.assertIsInstance(content, list)
        self.assertEqual(content[0].get("type"), "text")
        self.assertEqual(content[0].get("text"), "describe this image")
        self.assertEqual(content[1].get("type"), "image_url")
        self.assertEqual(content[1].get("image_url", {}).get("url"), "data:image/png;base64,AAAA")

    def test_live_test_default_hint_added_for_visible_testing_requests(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        hint = live_test_default_hint("Please test this UI behavior in browser and verify it works.")
        self.assertIn("live visible execution in Chrome", hint)

    def test_live_test_default_hint_skips_when_shadow_requested(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        hint = live_test_default_hint("Run a shadow headless browser test for this UI.")
        self.assertEqual(hint, "")

    def test_best_practice_gate_hint_generated_for_non_coder_request(self) -> None:
        hint = best_practice_gate_hint("I don't know how to code. Please always give the robust best practice method.")
        self.assertIn("<input_continuity_hint>", hint)
        self.assertIn("robust best-practice guidance", hint)

    def test_best_practice_gate_hint_injected_into_system_prompt_and_report(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        llm = CaptureLLM("use this approach")
        agent = AgentLoop(cfg, llm, tools, conversation=[])

        async def run_once():
            events = []
            async for ev in agent.run("idk how to code, make this always use the robust best practice method"):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        system_msg = next((m for m in llm.last_messages if m.get("role") == "system"), {})
        self.assertIn("robust best-practice guidance by default", str(system_msg.get("content") or ""))
        done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
        self.assertIsNotNone(done)
        assert done is not None
        continuity = (done.data.get("token_report") or {}).get("continuity") or {}
        self.assertTrue(bool(continuity.get("best_practice_gate_active")))

    def test_best_practice_gate_forced_by_non_coder_profile(self) -> None:
        cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
        tools = ToolRegistry()
        llm = CaptureLLM("hello")
        agent = AgentLoop(
            cfg,
            llm,
            tools,
            conversation=[],
            non_coder_profile=True,
            profile_type="non_coder",
        )

        async def run_once():
            events = []
            async for ev in agent.run("hey there"):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        system_msg = next((m for m in llm.last_messages if m.get("role") == "system"), {})
        self.assertIn("robust best-practice guidance by default", str(system_msg.get("content") or ""))
        done = next((e for e in events if e.type == EventType.AGENT_DONE), None)
        self.assertIsNotNone(done)
        assert done is not None
        continuity = (done.data.get("token_report") or {}).get("continuity") or {}
        self.assertTrue(bool(continuity.get("best_practice_gate_active")))
        self.assertEqual(str(continuity.get("best_practice_gate_source") or ""), "profile_non_coder")
        self.assertEqual(str(continuity.get("profile_type") or ""), "non_coder")
