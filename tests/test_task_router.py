"""Task router + data-driven team composition (Step 2)."""

from __future__ import annotations

import unittest

from thomas.marketplace.orchestrator import task_router
from thomas.marketplace.orchestrator.bot_roster import Bot


class TestTaskRouter(unittest.TestCase):
    def test_classify_common_tasks(self):
        self.assertEqual(task_router.classify_task("there's a bug in login").task_type, "fix-bug")
        self.assertEqual(task_router.classify_task("research the best vector db").task_type, "research-topic")
        self.assertEqual(task_router.classify_task("do a security audit on this").task_type, "security-audit")
        self.assertEqual(task_router.classify_task("build me a snake game").task_type, "build-feature")
        self.assertEqual(task_router.classify_task("refactor this module").task_type, "refactor-code")
        # nothing matches -> general
        self.assertEqual(task_router.classify_task("hello there friend").task_type, "general")

    def test_route_carries_team_and_effort(self):
        route = task_router.classify_task("do a security audit")
        self.assertEqual(route.team_key, "red-team")
        self.assertEqual(route.default_effort, "exhaustive")

    def test_team_size_scales_with_effort(self):
        route = task_router.classify_task("build me a feature")
        brisk = task_router.assemble_team(route, "brisk", 3)
        diligent = task_router.assemble_team(route, "diligent", 3)
        exhaustive = task_router.assemble_team(route, "exhaustive", 3)
        self.assertEqual(len(brisk), 1)
        self.assertGreaterEqual(len(diligent), 2)
        self.assertGreater(len(exhaustive), len(diligent))

    def test_no_bot_staffed_twice(self):
        route = task_router.classify_task("do a security audit")
        crew = task_router.assemble_team(route, "exhaustive", 4)
        bot_ids = [bot.id for _spec, bot in crew]
        self.assertEqual(len(bot_ids), len(set(bot_ids)))
        for _spec, bot in crew:
            self.assertIsInstance(bot, Bot)

    def test_exhaustive_adds_a_critic_role(self):
        route = task_router.classify_task("build me a feature")
        crew = task_router.assemble_team(route, "exhaustive", 4)
        specialties = [spec for spec, _bot in crew]
        self.assertIn("critic", specialties)

    def test_autonomy_coupling_caps_the_team(self):
        # Exhaustive @ L2 couples DOWN to Diligent -> smaller crew than @ L3.
        route = task_router.classify_task("build me a feature")
        low = task_router.assemble_team(route, "exhaustive", 2)
        high = task_router.assemble_team(route, "exhaustive", 3)
        self.assertLess(len(low), len(high))

    def test_quick_fix_is_solo_brisk(self):
        route = task_router.classify_task("just fix a typo in the readme")
        self.assertEqual(route.task_type, "quick-fix")
        self.assertEqual(route.default_effort, "brisk")
        crew = task_router.assemble_team(route, route.default_effort, 3)
        self.assertEqual(len(crew), 1)


if __name__ == "__main__":
    unittest.main()
