"""Branch-freshness enforcement (worktree_branch_guard).

Root cause of the 2026-06-14 stale-branch incident: an agent worked a week on a
branch cut off an old `dev` (which had since moved ~6 commits), and Praxis never
noticed because (a) `dev` wasn't a recognized base, (b) the guard only checked
topic-branch *stacking* not *freshness*, and (c) the whole guard was suppressible
by QuickBuilder. This locks the fix in stone: committing on a stale base is blocked.
"""

import unittest
from unittest.mock import patch

from scripts.forge.gates import worktree_branch_guard as g


class TestFreshnessDecision(unittest.TestCase):
    def test_over_limit_is_violation(self):
        self.assertTrue(g.freshness_violation(6, limit=5))
        self.assertTrue(g.freshness_violation(100, limit=5))

    def test_at_or_under_limit_is_ok(self):
        self.assertFalse(g.freshness_violation(5, limit=5))
        self.assertFalse(g.freshness_violation(0, limit=5))

    def test_unknown_is_not_a_violation(self):
        # Can't determine staleness (detached HEAD, base missing) -> don't false-block.
        self.assertFalse(g.freshness_violation(None, limit=5))

    def test_default_limit_catches_the_real_incident(self):
        # The 2026-06-14 branch was 6 commits behind dev. With the shipped default
        # it MUST be blocked — a double-digit limit would have been useless theater.
        self.assertLessEqual(g._MAX_COMMITS_BEHIND_BASE, 6)
        self.assertTrue(g.freshness_violation(6, limit=g._MAX_COMMITS_BEHIND_BASE))


class TestFreshnessFailure(unittest.TestCase):
    def test_stale_topic_branch_fails_with_rebase_guidance(self):
        with patch.object(g, "_commits_behind", return_value=6):
            lines = g._branch_freshness_failure("claude/some-topic-branch")
        self.assertTrue(lines, "a 6-behind topic branch must fail")
        joined = " ".join(lines).lower()
        self.assertIn("behind", joined)
        self.assertIn("rebase", joined)  # tells the agent the actual fix

    def test_fresh_topic_branch_passes(self):
        with patch.object(g, "_commits_behind", return_value=0):
            self.assertEqual(g._branch_freshness_failure("claude/fresh-branch"), [])

    def test_canonical_base_is_exempt(self):
        # dev/main/master are the bases themselves — never measured against.
        with patch.object(g, "_commits_behind", return_value=999):
            self.assertEqual(g._branch_freshness_failure("dev"), [])
            self.assertEqual(g._branch_freshness_failure("main"), [])

    def test_dev_is_a_recognized_base(self):
        # The exact gap that caused the incident: dev must be a canonical base.
        self.assertIn("dev", g.CANONICAL_BASE_BRANCHES)
        self.assertEqual(g._INTEGRATION_BASES[0], "dev")


if __name__ == "__main__":
    unittest.main()
