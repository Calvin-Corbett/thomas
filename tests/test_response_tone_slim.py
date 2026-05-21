"""Tests for simplified thomas.agent.response_tone module."""

import unittest

from thomas.agent.response_tone import (
    apply_directness_constraints,
    apply_social_tone_adjustments,
    live_test_default_hint,
    prompt_has_frustration_signal,
    prompt_requests_code_output,
    prompt_requests_directness_constraints,
    prompt_requests_structured_output,
    response_has_ack_signal,
    simplified_review_default_hint,
    strip_internal_reasoning_narration,
    strip_robotic_opener,
    strip_tool_call_artifacts,
    strip_unprompted_workspace_references,
)


class TestStripRoboticOpener(unittest.TestCase):
    def test_strips_certainly(self):
        out, changed = strip_robotic_opener("Certainly! Here's your answer.")
        self.assertTrue(changed)
        self.assertNotIn("Certainly", out)

    def test_preserves_got_it(self):
        # "Got it" is natural conversational language — should NOT be stripped
        out, changed = strip_robotic_opener("Got it, I'll help with that.")
        self.assertFalse(changed)
        self.assertIn("Got it", out)

    def test_strips_absolutely(self):
        out, changed = strip_robotic_opener("Absolutely! Let me help.")
        self.assertTrue(changed)

    def test_preserves_normal_text(self):
        out, changed = strip_robotic_opener("The function returns True.")
        self.assertFalse(changed)
        self.assertEqual(out, "The function returns True.")

    def test_empty_string(self):
        out, changed = strip_robotic_opener("")
        self.assertFalse(changed)


class TestStripInternalReasoning(unittest.TestCase):
    def test_strips_thinking_block(self):
        text = "<thinking>Let me analyze this...</thinking>The answer is 42."
        out, changed = strip_internal_reasoning_narration(text)
        self.assertTrue(changed)
        self.assertNotIn("thinking", out.lower())
        self.assertIn("42", out)

    def test_strips_reasoning_fence(self):
        text = "```reasoning\nStep 1: Think about it.\n```\nThe answer is 42."
        out, changed = strip_internal_reasoning_narration(text)
        self.assertTrue(changed)
        self.assertIn("42", out)

    def test_strips_as_ai_prefix(self):
        text = "As an AI language model, I think the answer is 42."
        out, changed = strip_internal_reasoning_narration(text)
        self.assertTrue(changed)
        self.assertNotIn("As an AI", out)

    def test_preserves_normal_text(self):
        text = "The function works by iterating through the list."
        out, changed = strip_internal_reasoning_narration(text)
        self.assertFalse(changed)

    def test_empty_string(self):
        out, changed = strip_internal_reasoning_narration("")
        self.assertFalse(changed)

    def test_preserves_python_indentation_for_code_prompt(self):
        text = "Let me think this through.\n    value = 1\n        nested = 2\n    return value"
        out, changed = strip_internal_reasoning_narration(
            text,
            prompt_text="Return ONLY the Python code continuation. No explanations.",
        )
        self.assertTrue(changed)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertTrue(lines[0].startswith("    "))
        self.assertIn("nested = 2", out)


class TestStripToolCallArtifacts(unittest.TestCase):
    def test_strips_json_tool_call(self):
        text = 'Here is the result. {"name": "search", "arguments": {"q": "test"}} Done.'
        out, changed = strip_tool_call_artifacts(text)
        self.assertTrue(changed)
        self.assertNotIn('"arguments"', out)

    def test_preserves_when_structured_requested(self):
        text = '{"name": "search", "arguments": {"q": "test"}}'
        out, changed = strip_tool_call_artifacts(text, prompt_text="show me the json output")
        self.assertFalse(changed)

    def test_preserves_normal_json(self):
        text = 'The config is {"port": 8080, "host": "localhost"}.'
        out, changed = strip_tool_call_artifacts(text)
        self.assertFalse(changed)

    def test_preserves_indentation_for_code_like_output(self):
        text = '{"name":"search","arguments":{"q":"x"}}\n    for i in range(3):\n        total += i\n    return total\n'
        out, changed = strip_tool_call_artifacts(
            text,
            prompt_text="give me only python code",
        )
        self.assertFalse(changed)
        self.assertIn("\n    for i in range(3):", out)
        self.assertIn("total += i", out)


class TestApplyDirectnessConstraints(unittest.TestCase):
    def test_one_sentence(self):
        text = "First sentence. Second sentence. Third sentence."
        out, changed = apply_directness_constraints(text, prompt_text="give me one sentence")
        self.assertTrue(changed)
        self.assertEqual(out, "First sentence.")

    def test_brief(self):
        text = " ".join(["word"] * 60)
        out, changed = apply_directness_constraints(text, prompt_text="keep it brief")
        self.assertTrue(changed)
        self.assertLessEqual(len(out.split()), 42)

    def test_first_step(self):
        text = "You should check the logs. Then restart the server. Then verify."
        out, changed = apply_directness_constraints(text, prompt_text="what's the first step?")
        self.assertTrue(changed)
        self.assertIn("logs", out)

    def test_no_constraint(self):
        text = "Here is a normal response."
        out, changed = apply_directness_constraints(text, prompt_text="tell me about it")
        self.assertFalse(changed)


class TestApplySocialToneAdjustments(unittest.TestCase):
    def test_strips_opener(self):
        out, changed = apply_social_tone_adjustments("Certainly! Here you go.", prompt_text="help")
        self.assertTrue(changed)
        self.assertNotIn("Certainly", out)

    def test_normal_text_unchanged(self):
        out, changed = apply_social_tone_adjustments("The fix is on line 42.", prompt_text="help")
        self.assertFalse(changed)

    def test_code_prompt_skips_social_whitespace_edits(self):
        text = "Certainly.\n    x = 1\n        y = 2"
        out, changed = apply_social_tone_adjustments(
            text,
            prompt_text="Return only Python code.",
        )
        self.assertFalse(changed)
        self.assertEqual(out, text)


class TestSignalDetection(unittest.TestCase):
    def test_frustration_detected(self):
        self.assertTrue(prompt_has_frustration_signal("this is so frustrating"))
        self.assertTrue(prompt_has_frustration_signal("you're too robotic"))

    def test_no_frustration(self):
        self.assertFalse(prompt_has_frustration_signal("help me fix this"))

    def test_ack_signal(self):
        self.assertTrue(response_has_ack_signal("you're right about that"))

    def test_no_ack_signal(self):
        self.assertFalse(response_has_ack_signal("here is the code"))

    def test_structured_output(self):
        self.assertTrue(prompt_requests_structured_output("give me json output"))
        self.assertFalse(prompt_requests_structured_output("fix the bug"))

    def test_code_output_detection(self):
        self.assertTrue(prompt_requests_code_output("Return ONLY the Python code continuation."))
        self.assertFalse(prompt_requests_code_output("Explain your approach."))

    def test_directness_constraints(self):
        self.assertTrue(prompt_requests_directness_constraints("one sentence please"))
        self.assertTrue(prompt_requests_directness_constraints("keep it brief"))
        self.assertFalse(prompt_requests_directness_constraints("explain it all"))


class TestWorkspaceReferences(unittest.TestCase):
    def test_strips_workspace_in_prompt(self):
        text = "What do you want to work on in `/home/user/project`?"
        out, changed = strip_unprompted_workspace_references(text, prompt_text="hello")
        self.assertTrue(changed)
        self.assertNotIn("/home/user/project", out)

    def test_preserves_when_asked_about_path(self):
        text = "You are in `/home/user/project`."
        out, changed = strip_unprompted_workspace_references(text, prompt_text="what directory am I in?")
        self.assertFalse(changed)


class TestLiveTestHint(unittest.TestCase):
    def test_browser_test_hint(self):
        hint = live_test_default_hint("run a browser ui test")
        self.assertIn("visible", hint.lower())

    def test_no_hint_for_normal(self):
        hint = live_test_default_hint("fix the bug")
        self.assertEqual(hint, "")

    def test_no_hint_for_headless(self):
        hint = live_test_default_hint("run headless browser test")
        self.assertEqual(hint, "")


class TestSimplifiedReviewHint(unittest.TestCase):
    def test_hint_enabled_for_simple_depth(self):
        hint = simplified_review_default_hint("simple")
        self.assertIn("good/bad", hint.lower())

    def test_hint_enabled_for_non_coder_adaptive(self):
        hint = simplified_review_default_hint("adaptive", non_coder_profile=True)
        self.assertIn("plain-language", hint.lower())

    def test_hint_disabled_for_technical_depth(self):
        hint = simplified_review_default_hint("technical", non_coder_profile=True)
        self.assertEqual(hint, "")


if __name__ == "__main__":
    unittest.main()
