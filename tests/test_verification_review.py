"""Verification gate (Step 6) + adversarial review (Step 7)."""

from __future__ import annotations

import unittest

from thomas.marketplace.orchestrator import adversarial_review as r
from thomas.marketplace.orchestrator import verification as v


class TestVerification(unittest.TestCase):
    def test_dispatches_to_code_checker_for_code_tasks(self):
        seen = {}

        def checker(work_dir, result_text):
            seen["called"] = True
            return v.VerificationResult(True, "code", "stub", ("stub",))

        res = v.verify_deliverable("build-feature", "wd", "out", checkers={"code": checker})
        self.assertTrue(seen.get("called"))
        self.assertTrue(res.passed)

    def test_generic_family_passes_when_deliverable_present(self):
        self.assertTrue(v.verify_deliverable("research-topic", result_text="some findings").passed)
        self.assertFalse(v.verify_deliverable("research-topic", result_text="").passed)

    def test_run_ruff_check_is_defensive_without_workspace(self):
        res = v.run_ruff_check("", "")
        self.assertTrue(res.passed)  # no workspace -> does not fail the task
        self.assertEqual(res.family, "code")


class TestAdversarialReview(unittest.TestCase):
    def test_passes_when_all_scores_high(self):
        res = r.review_deliverable("work", {}, scorer=lambda w, rb, lens: 9.0)
        self.assertTrue(res.passed)
        self.assertEqual(res.reviewers, 3)

    def test_veto_fails_even_with_high_median(self):
        scores = iter([9.0, 9.0, 2.0])  # one reviewer vetoes
        res = r.review_deliverable("work", {}, scorer=lambda w, rb, lens: next(scores))
        self.assertTrue(res.vetoed)
        self.assertFalse(res.passed)

    def test_low_median_fails(self):
        res = r.review_deliverable("work", {}, scorer=lambda w, rb, lens: 5.0)
        self.assertFalse(res.passed)  # 5 < 6 threshold

    def test_budget_tight_uses_single_reviewer(self):
        res = r.review_deliverable("work", {}, scorer=lambda w, rb, lens: 8.0, budget_ok=False)
        self.assertEqual(res.reviewers, 1)
        self.assertTrue(res.passed)

    def test_scores_are_clamped(self):
        res = r.review_deliverable("work", {}, scorer=lambda w, rb, lens: 99.0)
        self.assertTrue(all(s <= 10.0 for s in res.scores))


if __name__ == "__main__":
    unittest.main()
