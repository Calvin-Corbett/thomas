"""Effort dial: public vocabulary, Effort<->Autonomy coupling, and cost estimation.

Step 1 of the control plane. "Effort" is the user-facing dial (Brisk/Diligent/
Exhaustive) over the internal token-economy levels (cheap/optimal/max).
"""

from __future__ import annotations

import unittest

from thomas.core import token_economy as te


class TestEffortDial(unittest.TestCase):
    def test_public_effort_names_alias_internal_levels(self):
        self.assertEqual(te.normalize_token_economy_level("brisk"), "cheap")
        self.assertEqual(te.normalize_token_economy_level("diligent"), "optimal")
        self.assertEqual(te.normalize_token_economy_level("exhaustive"), "max")
        # internal level names still accepted
        self.assertEqual(te.normalize_token_economy_level("max"), "max")
        # unknown -> safe default
        self.assertEqual(te.normalize_token_economy_level("bogus"), "optimal")

    def test_internal_to_effort_and_display(self):
        self.assertEqual(te.internal_to_effort("max"), "exhaustive")
        self.assertEqual(te.internal_to_effort("cheap"), "brisk")
        self.assertEqual(te.effort_display_name("optimal"), "Diligent")
        self.assertEqual(te.effort_display_name("exhaustive"), "Exhaustive")

    def test_effort_autonomy_coupling(self):
        # L1 (chat-only) caps everything to Brisk.
        self.assertEqual(te.effective_effort("exhaustive", 1), "cheap")
        self.assertEqual(te.effective_effort("diligent", 1), "cheap")
        # Exhaustive requires L3+; below that it steps down to Diligent.
        self.assertEqual(te.effective_effort("exhaustive", 2), "optimal")
        self.assertEqual(te.effective_effort("exhaustive", 3), "max")
        self.assertEqual(te.effective_effort("exhaustive", 4), "max")
        # L4 auto-promotes Brisk -> Diligent.
        self.assertEqual(te.effective_effort("brisk", 4), "optimal")
        # L3 leaves Brisk as-is.
        self.assertEqual(te.effective_effort("brisk", 3), "cheap")
        # bad autonomy value falls back to the default tier behavior.
        self.assertEqual(te.effective_effort("diligent", "oops"), "optimal")

    def test_estimate_passes_monotonic(self):
        _lo_b, hi_b = te.estimate_passes("brisk", 3)
        _lo_d, hi_d = te.estimate_passes("diligent", 3)
        _lo_e, hi_e = te.estimate_passes("exhaustive", 3)
        self.assertLess(hi_b, hi_d)
        self.assertLess(hi_d, hi_e)

    def test_cost_scales_with_team(self):
        _lo1, hi1 = te.estimate_token_cost("exhaustive", 3, team_size=1)
        _lo3, hi3 = te.estimate_token_cost("exhaustive", 3, team_size=3)
        self.assertEqual(hi3, hi1 * 3)

    def test_within_budget(self):
        # No cap -> always fits.
        self.assertTrue(te.within_budget("exhaustive", 3, None))
        self.assertTrue(te.within_budget("exhaustive", 3, 0))
        # A tiny cap does not fit Exhaustive.
        self.assertFalse(te.within_budget("exhaustive", 3, 1000))
        # Brisk fits a cap equal to its worst-case estimate.
        _lo, hi = te.estimate_token_cost("brisk", 3)
        self.assertTrue(te.within_budget("brisk", 3, hi))

    def test_degrade_to_budget(self):
        # Generous budget -> no degradation.
        level, team = te.degrade_to_budget("exhaustive", 3, 10_000_000, team_size=4)
        self.assertEqual(level, "max")
        self.assertEqual(team, 4)
        # Tiny budget -> shrink the team to 1 and step Effort down to the floor.
        level, team = te.degrade_to_budget("exhaustive", 3, 1000, team_size=4)
        self.assertEqual(team, 1)
        self.assertEqual(level, "cheap")


if __name__ == "__main__":
    unittest.main()
