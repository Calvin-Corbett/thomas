"""Tests for improved thomas.agent.routing module."""

import unittest

from thomas.agent.routing import (
    PATH_CASUAL,
    PATH_CODING,
    PATH_DEBUG,
    PATH_GENERAL,
    PATH_META,
    PATH_PERSONAL,
    PATH_PLANNING,
    PATH_RESEARCH,
    IntentRouter,
)


class TestIntentRouter(unittest.TestCase):
    def setUp(self):
        self.router = IntentRouter()

    # ── Basic Routing ────────────────────────────────────────

    def test_greeting_routes_casual(self):
        d = self.router.decide("hey what's up")
        self.assertEqual(d.path, PATH_CASUAL)

    def test_coding_keywords(self):
        d = self.router.decide("refactor the authentication module")
        self.assertEqual(d.path, PATH_CODING)

    def test_debug_error_signal(self):
        d = self.router.decide("Traceback: error in main.py line 42")
        self.assertEqual(d.path, PATH_DEBUG)

    def test_planning_keywords(self):
        d = self.router.decide("create a roadmap for the project")
        self.assertEqual(d.path, PATH_PLANNING)

    def test_research_keywords(self):
        d = self.router.decide("research the latest trends in AI")
        self.assertEqual(d.path, PATH_RESEARCH)

    def test_personal_topic(self):
        d = self.router.decide("i feel stressed about my family")
        self.assertEqual(d.path, PATH_PERSONAL)

    # ── Critical Fix: "fix how you talk" ─────────────────────

    def test_fix_conversation_style_not_coding(self):
        """'fix how you talk' should NOT route to coding."""
        d = self.router.decide("fix how you talk, you sound robotic")
        self.assertNotEqual(d.path, PATH_CODING)
        self.assertIn(d.path, [PATH_META, PATH_PERSONAL])

    def test_fix_too_robotic(self):
        d = self.router.decide("you're too robotic, talk better")
        self.assertEqual(d.path, PATH_META)

    def test_fix_with_code_context(self):
        """'fix the bug in auth.py' SHOULD route to coding."""
        d = self.router.decide("fix the bug in auth.py")
        self.assertIn(d.path, [PATH_CODING, PATH_DEBUG])

    def test_fix_ambiguous(self):
        """'fix it' without context should not default to coding."""
        d = self.router.decide("fix it")
        self.assertNotEqual(d.path, PATH_CODING)

    def test_behavior_feedback(self):
        d = self.router.decide("talking to you sucks, be more human")
        self.assertEqual(d.path, PATH_META)

    # ── Tools Policy Changes ─────────────────────────────────

    def test_casual_allows_tools(self):
        """Casual chat should now allow tools (was 'never')."""
        d = self.router.decide("hey there")
        self.assertEqual(d.tools_policy, "auto")

    def test_personal_allows_tools(self):
        d = self.router.decide("i feel stressed about work")
        self.assertEqual(d.tools_policy, "auto")

    def test_meta_allows_tools(self):
        d = self.router.decide("how do you work")
        self.assertEqual(d.tools_policy, "auto")

    # ── Memory Budget Improvements ───────────────────────────

    def test_casual_memory_budget_increased(self):
        d = self.router.decide("hey what's going on")
        self.assertGreaterEqual(d.memory_budget_tokens, 800)

    def test_personal_memory_budget(self):
        d = self.router.decide("my family situation")
        self.assertGreaterEqual(d.memory_budget_tokens, 700)

    # ── Follow-up Routing ────────────────────────────────────

    def test_followup_bias(self):
        """Follow-ups should bias toward prior route."""
        d = self.router.decide(
            "yeah that one",
            is_followup=True,
            prior_route=PATH_CODING,
        )
        self.assertEqual(d.path, PATH_CODING)
        self.assertTrue(d.is_followup)

    def test_followup_flag_preserved(self):
        d = self.router.decide("ok", is_followup=True, prior_route=PATH_DEBUG)
        self.assertTrue(d.is_followup)

    # ── Troubleshooting Context ──────────────────────────────

    def test_troubleshoot_with_code_context(self):
        d = self.router.decide("the server is broken and not working")
        # Without code keywords, should be general not debug
        self.assertIn(d.path, [PATH_GENERAL, PATH_DEBUG, PATH_CASUAL])

    def test_troubleshoot_with_code(self):
        d = self.router.decide("the function is broken and throwing errors")
        self.assertIn(d.path, [PATH_DEBUG, PATH_CODING])

    # ── RouteDecision Structure ──────────────────────────────

    def test_route_decision_to_dict(self):
        d = self.router.decide("hello")
        data = d.to_dict()
        self.assertIn("path", data)
        self.assertIn("confidence", data)
        self.assertIn("is_followup", data)

    def test_confidence_range(self):
        d = self.router.decide("refactor the codebase")
        self.assertGreaterEqual(d.confidence, 0.35)
        self.assertLessEqual(d.confidence, 0.99)

    def test_reasons_populated(self):
        d = self.router.decide("debug the authentication bug")
        self.assertGreater(len(d.reasons), 0)

    # ── Edge Cases ───────────────────────────────────────────

    def test_empty_input(self):
        d = self.router.decide("")
        self.assertEqual(d.path, PATH_CASUAL)

    def test_no_execution_intent(self):
        d = self.router.decide("i didn't give you a task, just talking")
        self.assertIn(d.path, [PATH_CASUAL, PATH_META])

    def test_liveness_check(self):
        d = self.router.decide("are you there?")
        self.assertEqual(d.path, PATH_CASUAL)

    def test_override_mode(self):
        d = self.router.decide("hello", requested_mode="thinking")
        self.assertEqual(d.mode, "thinking")

    def test_override_tools_policy(self):
        d = self.router.decide("hello", requested_tools_policy="always")
        self.assertEqual(d.tools_policy, "always")


if __name__ == "__main__":
    unittest.main()
