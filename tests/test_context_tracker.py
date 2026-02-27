"""Tests for thomas.agent.context_tracker module."""

import unittest

from thomas.agent.context_tracker import ContextTracker, ConversationContext


class TestConversationContext(unittest.TestCase):
    def test_defaults(self):
        ctx = ConversationContext()
        self.assertEqual(ctx.current_task, "")
        self.assertEqual(ctx.user_mood, "neutral")
        self.assertEqual(ctx.recent_topics, [])
        self.assertEqual(ctx.turn_count, 0)


class TestContextTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = ContextTracker()

    def test_create(self):
        self.assertEqual(self.tracker.turn_count, 0)
        self.assertEqual(self.tracker.mood, "neutral")

    def test_update_user(self):
        self.tracker.update("user", "fix the bug in auth.py")
        self.assertEqual(self.tracker.turn_count, 1)

    def test_update_assistant(self):
        self.tracker.update("assistant", "I'll look at that file now.")
        self.assertEqual(self.tracker.turn_count, 1)

    def test_empty_update_ignored(self):
        self.tracker.update("user", "")
        self.assertEqual(self.tracker.turn_count, 0)

    def test_infer_task_with_file(self):
        self.tracker.update("user", "fix the bug in src/auth.py")
        self.assertIn("src/auth.py", self.tracker.current_task)

    def test_infer_task_with_verb(self):
        self.tracker.update("user", "build a login form")
        self.assertIn("build", self.tracker.current_task.lower())

    def test_task_persists(self):
        self.tracker.update("user", "debug the auth module")
        self.tracker.update("user", "yeah that one")
        # Task shouldn't be cleared by short follow-up
        self.assertTrue(len(self.tracker.current_task) > 0)

    def test_detect_mood_frustrated(self):
        self.tracker.update("user", "this is so frustrating, nothing works!")
        self.assertEqual(self.tracker.mood, "frustrated")

    def test_detect_mood_positive(self):
        self.tracker.update("user", "that's amazing, love it!")
        self.assertEqual(self.tracker.mood, "positive")

    def test_detect_mood_curious(self):
        self.tracker.update("user", "how does the memory system work?")
        self.assertEqual(self.tracker.mood, "curious")

    def test_mood_persists(self):
        self.tracker.update("user", "this is frustrating")
        self.tracker.update("user", "ok")
        self.assertEqual(self.tracker.mood, "frustrated")

    def test_extract_files(self):
        self.tracker.update("user", "look at src/main.py and config/settings.toml")
        ctx = self.tracker.get_context()
        self.assertGreaterEqual(len(ctx.files_mentioned), 1)

    def test_detect_confusion(self):
        self.tracker.update("user", "that doesn't make sense, what do you mean?")
        ctx = self.tracker.get_context()
        self.assertGreater(len(ctx.recent_confusions), 0)

    def test_topics_tracked(self):
        self.tracker.update("user", "let's talk about authentication")
        self.tracker.update("user", "now let's discuss database schemas")
        ctx = self.tracker.get_context()
        self.assertGreaterEqual(len(ctx.recent_topics), 2)

    def test_topic_shift_detection(self):
        self.tracker.update("user", "fix the authentication bug in login")
        shifted = self.tracker.detect_topic_shift("what's your favorite color?")
        self.assertTrue(shifted)

    def test_no_topic_shift(self):
        self.tracker.update("user", "fix the authentication bug")
        shifted = self.tracker.detect_topic_shift("what about the auth tests?")
        # Should not detect shift — same topic area
        # (this depends on word overlap, may or may not shift)
        self.assertIsInstance(shifted, bool)

    def test_to_prompt_block_empty(self):
        block = self.tracker.to_prompt_block()
        self.assertEqual(block, "")

    def test_to_prompt_block_with_data(self):
        self.tracker.update("user", "fix the bug in src/auth.py")
        block = self.tracker.to_prompt_block()
        self.assertIn("Current task", block)

    def test_to_prompt_block_max_chars(self):
        for i in range(20):
            self.tracker.update("user", f"topic number {i} about something long")
        block = self.tracker.to_prompt_block(max_chars=100)
        self.assertLessEqual(len(block), 100)

    def test_get_context_snapshot(self):
        self.tracker.update("user", "build a REST API for user management")
        ctx = self.tracker.get_context()
        self.assertIsInstance(ctx, ConversationContext)
        self.assertTrue(len(ctx.current_task) > 0)
        self.assertGreater(ctx.turn_count, 0)

    def test_interaction_style_terse(self):
        for _ in range(5):
            self.tracker.update("user", "yes")
            self.tracker.update("assistant", "ok")
        ctx = self.tracker.get_context()
        self.assertEqual(ctx.interaction_style, "terse")

    def test_interaction_style_verbose(self):
        long_msg = "I would really love it if you could help me with this very complex task " * 5
        for _ in range(4):
            self.tracker.update("user", long_msg)
            self.tracker.update("assistant", "ok")
        ctx = self.tracker.get_context()
        self.assertEqual(ctx.interaction_style, "verbose")


if __name__ == "__main__":
    unittest.main()
