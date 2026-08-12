"""Structured task analysis validation."""

from __future__ import annotations

import unittest

from thomas.core.task_decomposer import TaskAnalysis, normalize_task_analysis


class TestTaskDecomposer(unittest.TestCase):
    def test_missing_analysis_uses_neutral_no_review_default(self):
        analysis = normalize_task_analysis()
        self.assertEqual(analysis.clarity_score, 100)
        self.assertEqual(analysis.complexity, "unspecified")
        self.assertEqual(analysis.recommended_effort, "")
        self.assertFalse(analysis.needs_intent_review)

    def test_structured_analysis_is_preserved(self):
        analysis = normalize_task_analysis(
            {
                "clarity_score": 35,
                "complexity": "hard",
                "recommended_effort": "exhaustive",
                "needs_intent_review": True,
            }
        )
        self.assertEqual(analysis, TaskAnalysis(35, "hard", "exhaustive", True))

    def test_invalid_fields_are_safely_normalized(self):
        analysis = normalize_task_analysis(
            {
                "clarity_score": 900,
                "complexity": "invented",
                "recommended_effort": "infinite",
            }
        )
        self.assertEqual(analysis.clarity_score, 100)
        self.assertEqual(analysis.complexity, "unspecified")
        self.assertEqual(analysis.recommended_effort, "")


if __name__ == "__main__":
    unittest.main()
