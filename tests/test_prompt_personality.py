"""Tests for thomas.agent.prompt_templates enhanced personality system."""

import unittest

from thomas.agent.prompt_templates import (
    LOW_INTENT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_default_system_prompt,
    build_route_system_prompt,
    format_input_continuity_hint,
    format_lessons_for_prompt,
    format_library_context,
    format_memory_context,
    inject_context_block,
    inject_lessons_block,
)


class TestSystemPromptPersonality(unittest.TestCase):
    def _built(self):
        return build_default_system_prompt(cwd="/", platform="linux", model_name="m", model_id="m")

    def test_system_prompt_has_personality(self):
        self.assertIn("sharp", self._built().lower())
        self.assertIn("witty", self._built().lower())

    def test_system_prompt_has_identity(self):
        self.assertIn("<identity>", self._built())
        self.assertIn("Thomas", self._built())
        self.assertIn("human assistant", self._built().lower())
        self.assertIn("can do anything on this computer", self._built().lower())

    def test_system_prompt_has_conversation_intelligence(self):
        self.assertIn("<conversational_intelligence>", self._built())

    def test_low_intent_has_personality_too(self):
        self.assertIn("{identity}", LOW_INTENT_SYSTEM_PROMPT)
        self.assertIn("{conversation_intelligence}", LOW_INTENT_SYSTEM_PROMPT)

    def test_low_intent_still_allows_tools(self):
        self.assertIn("tools", LOW_INTENT_SYSTEM_PROMPT.lower())

    def test_no_robotic_phrases(self):
        full = SYSTEM_PROMPT + LOW_INTENT_SYSTEM_PROMPT
        self.assertNotIn("Certainly", full)
        self.assertNotIn("Absolutely", full)

    def test_has_context_slot(self):
        self.assertIn("{context_block}", SYSTEM_PROMPT)

    def test_has_lessons_slot(self):
        self.assertIn("{lessons_block}", SYSTEM_PROMPT)


class TestBuildDefaultSystemPrompt(unittest.TestCase):
    def test_basic_build(self):
        prompt = build_default_system_prompt(
            cwd="/home/user",
            platform="linux",
            model_name="gpt-4",
            model_id="gpt-4-0125",
        )
        self.assertIn("Thomas", prompt)
        self.assertIn("/home/user", prompt)
        self.assertIn("gpt-4", prompt)

    def test_handles_empty_values(self):
        prompt = build_default_system_prompt(cwd="", platform="", model_name="", model_id="")
        self.assertIn("Thomas", prompt)

    def test_personality_present(self):
        prompt = build_default_system_prompt(cwd="/", platform="linux", model_name="m", model_id="m")
        self.assertIn("sharp", prompt.lower())


class TestBuildRouteSystemPrompt(unittest.TestCase):
    def test_execution_route(self):
        prompt = build_route_system_prompt(
            route_path="coding_task",
            cwd="/",
            platform="linux",
            model_name="m",
            model_id="m",
        )
        self.assertIn("execution_contract", prompt)

    def test_casual_route(self):
        prompt = build_route_system_prompt(
            route_path="casual_chat",
            cwd="/",
            platform="linux",
            model_name="m",
            model_id="m",
        )
        self.assertIn("conversation", prompt)
        self.assertNotIn("execution_contract", prompt)

    def test_with_context(self):
        prompt = build_route_system_prompt(
            route_path="coding_task",
            cwd="/",
            platform="linux",
            model_name="m",
            model_id="m",
            context_text="Working on auth module",
        )
        self.assertIn("Working on auth module", prompt)
        self.assertIn("<session_context>", prompt)

    def test_with_lessons(self):
        prompt = build_route_system_prompt(
            route_path="coding_task",
            cwd="/",
            platform="linux",
            model_name="m",
            model_id="m",
            lessons_text="User prefers short responses",
        )
        self.assertIn("User prefers short responses", prompt)
        self.assertIn("<learned_knowledge>", prompt)

    def test_empty_context_not_injected(self):
        prompt = build_route_system_prompt(
            route_path="coding_task",
            cwd="/",
            platform="linux",
            model_name="m",
            model_id="m",
            context_text="",
        )
        self.assertNotIn("<session_context>", prompt)

    def test_all_low_intent_paths(self):
        for path in ["casual_chat", "personal_context", "assistant_meta", "general"]:
            prompt = build_route_system_prompt(
                route_path=path,
                cwd="/",
                platform="linux",
                model_name="m",
                model_id="m",
            )
            self.assertNotIn("execution_contract", prompt)


class TestContextInjection(unittest.TestCase):
    def test_inject_context_block(self):
        block = inject_context_block("Working on login page")
        self.assertIn("<session_context>", block)
        self.assertIn("Working on login page", block)

    def test_inject_empty_context(self):
        block = inject_context_block("")
        self.assertEqual(block, "")

    def test_inject_lessons_block(self):
        block = inject_lessons_block("User likes verbose responses")
        self.assertIn("<learned_knowledge>", block)

    def test_inject_empty_lessons(self):
        block = inject_lessons_block("")
        self.assertEqual(block, "")


class TestFormatLessonsForPrompt(unittest.TestCase):
    def test_format_lessons(self):
        lessons = [
            {"type": "preference", "content": "User prefers Python", "confidence": 0.9},
            {"type": "fact", "content": "Project uses FastAPI", "confidence": 0.8},
        ]
        text = format_lessons_for_prompt(lessons)
        self.assertIn("[preference]", text)
        self.assertIn("[fact]", text)
        self.assertIn("Python", text)

    def test_format_empty(self):
        text = format_lessons_for_prompt([])
        self.assertEqual(text, "")

    def test_max_lessons(self):
        lessons = [{"type": "fact", "content": f"Lesson {i}"} for i in range(10)]
        text = format_lessons_for_prompt(lessons, max_lessons=3)
        self.assertEqual(text.count("- ["), 3)


class TestFormatHelpers(unittest.TestCase):
    def test_memory_context(self):
        result = format_memory_context("some memory")
        self.assertIn("<memory_context>", result)

    def test_continuity_hint(self):
        result = format_input_continuity_hint("working on auth")
        self.assertIn("<input_continuity_hint>", result)

    def test_library_context(self):
        result = format_library_context("research data")
        self.assertIn("<library_context>", result)


if __name__ == "__main__":
    unittest.main()
