"""Structured task routing and data-driven team composition."""

from __future__ import annotations

import unittest

from thomas.marketplace.orchestrator import task_router
from thomas.marketplace.orchestrator.bot_roster import Bot


class TestTaskRouter(unittest.TestCase):
    def test_task_prose_is_not_classified(self):
        for prose in (
            "there is a bug in login",
            "research the best vector db",
            "do a security audit on this",
            "build me a snake game",
        ):
            self.assertEqual(task_router.route_task(prose).task_type, "general")

    def test_exact_structured_task_type_selects_route(self):
        route = task_router.route_task("security-audit")
        self.assertEqual(route.task_type, "security-audit")
        self.assertEqual(route.team_key, "red-team")
        self.assertEqual(route.default_effort, "exhaustive")

    def test_structured_lead_specialty_overrides_neutral_lead(self):
        route = task_router.route_task(None, lead_specialty="coding")
        self.assertEqual(route.task_type, "general")
        self.assertEqual(route.lead_specialty, "coding")

    def test_team_size_scales_with_explicit_effort(self):
        route = task_router.route_task("build-feature")
        brisk = task_router.assemble_team(route, "brisk", 3)
        diligent = task_router.assemble_team(route, "diligent", 3)
        exhaustive = task_router.assemble_team(route, "exhaustive", 3)
        self.assertEqual(len(brisk), 1)
        self.assertGreaterEqual(len(diligent), 2)
        self.assertGreater(len(exhaustive), len(diligent))

    def test_no_bot_staffed_twice(self):
        route = task_router.route_task("security-audit")
        crew = task_router.assemble_team(route, "exhaustive", 4)
        bot_ids = [bot.id for _spec, bot in crew]
        self.assertEqual(len(bot_ids), len(set(bot_ids)))
        for _spec, bot in crew:
            self.assertIsInstance(bot, Bot)

    def test_explicit_specialties_are_not_expanded_from_effort(self):
        route = task_router.route_task(None)
        crew = task_router.assemble_team(
            route,
            "exhaustive",
            4,
            specialties=["data", "critic"],
        )
        self.assertEqual([specialty for specialty, _bot in crew], ["data", "critic"])

    def test_autonomy_coupling_caps_a_structured_team(self):
        route = task_router.route_task("build-feature")
        low = task_router.assemble_team(route, "exhaustive", 2)
        high = task_router.assemble_team(route, "exhaustive", 3)
        self.assertLess(len(low), len(high))

    def test_quick_fix_is_solo_brisk_when_explicit(self):
        route = task_router.route_task("quick-fix")
        self.assertEqual(route.default_effort, "brisk")
        crew = task_router.assemble_team(route, route.default_effort, 3)
        self.assertEqual(len(crew), 1)


if __name__ == "__main__":
    unittest.main()
