"""Effort dial: public vocabulary, Effort<->Autonomy coupling, and cost estimation.

Step 1 of the control plane. "Effort" is the user-facing dial (Brisk/Diligent/
Exhaustive) over the internal token-economy levels (cheap/optimal/max).
"""

from __future__ import annotations

import unittest

from thomas.core import token_economy as te
from thomas.core.runtime_profile import resolve_runtime_profile


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

    def test_estimate_passes_is_the_same_runaway_guard_at_every_effort(self):
        """Effort no longer rations passes, so the estimate cannot be monotonic.

        This test asserted 3 < 15 < 32 and was named ``..._monotonic`` until cd0203a7
        ("no pass limits -- the model stops when it is done, not when a counter says
        so") deleted the per-level rations. The same commit met this exact shape in
        test_agent_worker_parity and answered it by turning ``assertLess`` into
        ``assertEqual``; that is what happens here. Equality is the stronger guard now:
        a ladder of any size reappearing between the three efforts fails it.
        """
        lo_b, hi_b = te.estimate_passes("brisk", 3)
        lo_d, hi_d = te.estimate_passes("diligent", 3)
        lo_e, hi_e = te.estimate_passes("exhaustive", 3)
        self.assertEqual((lo_b, hi_b), (lo_d, hi_d))
        self.assertEqual((lo_d, hi_d), (lo_e, hi_e))
        # The one number left is the runaway guard, deliberately far above any real
        # task. token_economy.py's own comment says to lower reasoning effort instead.
        self.assertEqual(hi_e, 400)

    def test_compute_max_passes_tolerates_missing_config_value(self):
        # 10 / 25 / 3 were the old per-level rations. cd0203a7 removed the rationing
        # and left one 400-pass runaway guard at every level, so a missing or
        # unparseable config value now lands on the guard instead of on a small
        # number. What this test is actually for is unchanged and still asserted
        # below: bad config must be tolerated, not raised on.
        self.assertEqual(te.coerce_base_iterations(None), 10)
        self.assertEqual(te.coerce_base_iterations(0), 10)
        self.assertEqual(te.compute_max_passes("optimal", None), 400)
        self.assertEqual(te.compute_max_passes("max", None), 400)
        self.assertEqual(te.compute_max_passes("cheap", "not-a-number"), 400)

    def test_runtime_profile_tolerates_missing_config_value(self):
        # 30 was base_iterations x3 under the old "max" ration. Since cd0203a7 the
        # economy pass count is the 400 runaway guard, and L4's extended-iterations
        # boost only ever raises the count, so the profile resolves to the guard.
        profile = resolve_runtime_profile(autonomy_level=4, economy_level="max", base_iterations=None)
        self.assertEqual(profile.effective_max_iterations, 400)

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
