"""Tests for thomas.agent.conversation module."""

import unittest

from thomas.agent.conversation import ConversationIntelligence, TurnRecord


class TestTurnRecord(unittest.TestCase):
    def test_create(self):
        t = TurnRecord(role="user", text="hello")
        self.assertEqual(t.role, "user")
        self.assertEqual(t.topic, "")


class TestConversationIntelligence(unittest.TestCase):
    def setUp(self):
        self.ci = ConversationIntelligence()

    def test_create(self):
        self.assertEqual(self.ci.turn_count, 0)
        self.assertEqual(self.ci.current_topic, "")

    def test_update(self):
        self.ci.update("user", "fix the auth bug")
        self.assertEqual(self.ci.turn_count, 1)
        self.assertTrue(len(self.ci.current_topic) > 0)

    def test_update_empty_ignored(self):
        self.ci.update("user", "")
        self.assertEqual(self.ci.turn_count, 0)

    # ── Follow-up Detection ──────────────────────────────────

    def test_followup_short_message(self):
        self.ci.update("user", "fix the authentication bug in login.py")
        self.ci.update("assistant", "I'll look at that now.")
        self.assertTrue(self.ci.is_followup("and the tests?"))

    def test_followup_connector_word(self):
        self.ci.update("user", "how does memory work?")
        self.ci.update("assistant", "Memory uses an event-sourced architecture.")
        self.assertTrue(self.ci.is_followup("also what about the learning system?"))

    def test_followup_pronoun(self):
        self.ci.update("user", "explain the routing system")
        self.ci.update("assistant", "The router classifies messages into paths.")
        self.assertTrue(self.ci.is_followup("how does it handle ambiguity?"))

    def test_not_followup_long_new_topic(self):
        self.ci.update("user", "fix auth")
        self.ci.update("assistant", "done")
        result = self.ci.is_followup(
            "I want to build a completely new dashboard with charts "
            "and real-time updates using WebSocket connections and "
            "React components for the frontend rendering pipeline"
        )
        self.assertFalse(result)

    def test_not_followup_empty(self):
        self.assertFalse(self.ci.is_followup(""))

    # ── Reference Resolution ─────────────────────────────────

    def test_resolve_with_pronoun(self):
        self.ci.update("user", "look at the authentication module")
        self.ci.update("assistant", "The auth module handles JWT tokens.")
        resolved = self.ci.resolve_references("can you fix it?")
        self.assertIn("context", resolved)

    def test_no_resolve_without_pronoun(self):
        self.ci.update("user", "look at auth")
        self.ci.update("assistant", "ok")
        resolved = self.ci.resolve_references("build a new REST API endpoint for users")
        self.assertNotIn("context", resolved)

    def test_resolve_no_prior_context(self):
        resolved = self.ci.resolve_references("fix it")
        # No prior turns, can't resolve
        self.assertEqual(resolved, "fix it")

    # ── Confusion Detection ──────────────────────────────────

    def test_detect_explicit_confusion(self):
        self.assertTrue(self.ci.detect_confusion("what do you mean?"))

    def test_detect_misunderstanding(self):
        self.assertTrue(self.ci.detect_confusion("no i meant the other file"))

    def test_detect_huh(self):
        self.assertTrue(self.ci.detect_confusion("huh?"))

    def test_no_confusion(self):
        self.assertFalse(self.ci.detect_confusion("sounds good, let's proceed"))

    def test_detect_repeated_question(self):
        self.ci.update("user", "how does the routing system work?")
        self.ci.update("assistant", "It uses weighted scoring.")
        is_confused = self.ci.detect_confusion("how does the routing system work?")
        self.assertTrue(is_confused)

    # ── Topic Shift Detection ────────────────────────────────

    def test_topic_shift(self):
        self.ci.update("user", "fix the authentication login page bug")
        shifted = self.ci.detect_topic_shift("what's the weather like today?")
        self.assertTrue(shifted)

    def test_no_topic_shift(self):
        self.ci.update("user", "fix the authentication bug in the login module")
        shifted = self.ci.detect_topic_shift("what about the authentication login tests?")
        self.assertFalse(shifted)

    def test_topic_shift_no_prior(self):
        shifted = self.ci.detect_topic_shift("anything here")
        self.assertFalse(shifted)

    # ── Continuity Hint ──────────────────────────────────────

    def test_continuity_hint_empty(self):
        hint = self.ci.generate_continuity_hint()
        self.assertEqual(hint, "")

    def test_continuity_hint_with_topic(self):
        self.ci.update("user", "working on the auth module")
        hint = self.ci.generate_continuity_hint()
        self.assertIn("Discussing", hint)

    def test_continuity_hint_with_turns(self):
        self.ci.update("user", "fix auth")
        self.ci.update("assistant", "ok")
        self.ci.update("user", "and the tests")
        hint = self.ci.generate_continuity_hint()
        self.assertIn("Turn", hint)

    # ── Prior Route Hint ─────────────────────────────────────

    def test_prior_route_hint_none(self):
        self.assertIsNone(self.ci.get_prior_route_hint())

    def test_prior_route_hint_set(self):
        self.ci.update("user", "fix the database connection code")
        hint = self.ci.get_prior_route_hint()
        self.assertIsNotNone(hint)
        self.assertTrue(len(hint) > 0)


if __name__ == "__main__":
    unittest.main()
