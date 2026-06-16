"""Pre-dispatch task analysis (Step 3)."""

from __future__ import annotations

import unittest

from thomas.core.task_decomposer import INTENT_REVIEW_THRESHOLD, analyze_task


class TestTaskDecomposer(unittest.TestCase):
    def test_clear_well_specified_task_no_review(self):
        a = analyze_task(
            "Add a logout button to the navbar that clears the session so that the user returns to the login page"
        )
        self.assertGreaterEqual(a.clarity_score, INTENT_REVIEW_THRESHOLD)
        self.assertEqual(a.complexity, "moderate")
        self.assertFalse(a.needs_intent_review)

    def test_vague_task_low_clarity_triggers_review(self):
        a = analyze_task("just fix it somehow")
        self.assertLess(a.clarity_score, INTENT_REVIEW_THRESHOLD)
        self.assertTrue(a.needs_intent_review)

    def test_short_task_low_clarity(self):
        a = analyze_task("make it")
        self.assertLess(a.clarity_score, INTENT_REVIEW_THRESHOLD)

    def test_complex_task_is_hard_and_needs_review(self):
        a = analyze_task(
            "migrate the auth system across multiple services and integrate the distributed pipeline end to end"
        )
        self.assertEqual(a.complexity, "hard")
        self.assertTrue(a.needs_intent_review)
        self.assertEqual(a.recommended_effort, "diligent")

    def test_simple_task_recommends_brisk(self):
        a = analyze_task("print hello world")
        self.assertEqual(a.complexity, "simple")
        self.assertEqual(a.recommended_effort, "brisk")

    def test_clarity_is_bounded(self):
        for prompt in ("", "x", "a b c d e f g h i j k l m n o p"):
            a = analyze_task(prompt)
            self.assertGreaterEqual(a.clarity_score, 0)
            self.assertLessEqual(a.clarity_score, 100)


if __name__ == "__main__":
    unittest.main()
