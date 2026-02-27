"""Tests for thomas.agent.intelligence integration layer."""

import unittest

from thomas.agent.intelligence import IntelligenceLayer


class TestIntelligenceLayer(unittest.TestCase):
    def setUp(self):
        # Disable learning (may not have storage available in tests)
        self.intel = IntelligenceLayer(learning_enabled=False)

    def test_create(self):
        self.assertEqual(self.intel.turn_count, 0)
        self.assertEqual(self.intel.mood, "neutral")

    def test_update_user_message(self):
        self.intel.update_user_message("fix the auth bug in login.py")
        self.assertEqual(self.intel.turn_count, 1)
        self.assertTrue(len(self.intel.current_task) > 0)

    def test_update_assistant_message(self):
        self.intel.update_assistant_message("I'll look at that now.")
        self.assertEqual(self.intel.turn_count, 1)

    def test_followup_detection(self):
        self.intel.update_user_message("fix the auth bug in login.py")
        self.intel.update_assistant_message("Looking at it now.")
        self.assertTrue(self.intel.is_followup("and the tests?"))

    def test_confusion_detection(self):
        self.assertTrue(self.intel.detect_confusion("what do you mean?"))
        self.assertFalse(self.intel.detect_confusion("sounds good"))

    def test_context_text(self):
        self.intel.update_user_message("debug the payment module")
        text = self.intel.get_context_text()
        self.assertIn("Current task", text)

    def test_context_text_empty(self):
        text = self.intel.get_context_text()
        self.assertEqual(text, "")

    def test_lessons_text_disabled(self):
        text = self.intel.get_lessons_text("fix auth")
        self.assertEqual(text, "")

    def test_continuity_hint(self):
        self.intel.update_user_message("working on the router")
        hint = self.intel.get_continuity_hint()
        self.assertIn("Discussing", hint)

    def test_continuity_hint_empty(self):
        hint = self.intel.get_continuity_hint()
        self.assertEqual(hint, "")

    def test_mood_tracking(self):
        self.intel.update_user_message("this is so frustrating!")
        self.assertEqual(self.intel.mood, "frustrated")

    def test_mood_positive(self):
        self.intel.update_user_message("awesome, that's perfect!")
        self.assertEqual(self.intel.mood, "positive")

    def test_learn_does_nothing_when_disabled(self):
        # Should not raise even when learning is disabled
        self.intel.learn_from_interaction("hello", "hi there", 0.9)

    def test_learning_enabled_property(self):
        self.assertFalse(self.intel.learning_enabled)

    def test_prior_route_hint(self):
        self.intel.update_user_message("fix the auth module")
        hint = self.intel.get_prior_route_hint()
        self.assertIsNotNone(hint)

    def test_prior_route_hint_empty(self):
        hint = self.intel.get_prior_route_hint()
        self.assertIsNone(hint)

    def test_multi_turn_conversation(self):
        self.intel.update_user_message("build a REST API")
        self.intel.update_assistant_message("I'll create the endpoints.")
        self.intel.update_user_message("add authentication too")
        self.intel.update_assistant_message("Adding JWT auth.")
        self.intel.update_user_message("and tests")

        self.assertEqual(self.intel.turn_count, 5)
        self.assertTrue(self.intel.is_followup("and tests"))
        ctx = self.intel.get_context_text()
        self.assertTrue(len(ctx) > 0)


if __name__ == "__main__":
    unittest.main()
