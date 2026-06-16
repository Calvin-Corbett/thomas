"""Live wiring of the Exhaustive pipeline into the dispatch path (Step 8)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from thomas.server import exhaustive_runtime as er


class TestExhaustiveRouting(unittest.TestCase):
    def test_is_exhaustive(self):
        self.assertTrue(er.is_exhaustive("exhaustive"))
        self.assertTrue(er.is_exhaustive("max"))
        self.assertFalse(er.is_exhaustive("diligent"))
        self.assertFalse(er.is_exhaustive("brisk"))
        # exhaustive at the lowest autonomy couples down -> not exhaustive
        self.assertFalse(er.is_exhaustive("exhaustive", autonomy_level=1))

    def test_heuristic_scorer_rewards_substance(self):
        good = er._heuristic_scorer("a long substantive deliverable " * 4, {"verified": True}, "x")
        bad = er._heuristic_scorer("err failed error", {}, "x")
        self.assertGreater(good, bad)
        self.assertLessEqual(good, 10.0)


class TestRunExhaustivePipeline(unittest.IsolatedAsyncioTestCase):
    async def test_runs_pipeline_with_real_worker_build(self):
        async def fake_worker_events(app, **kwargs):  # noqa: ANN001, ANN003
            yield {"type": "tool_start", "name": "fs.write_file"}
            yield {"type": "text", "text": "Built a snake game in game.html. Main file: game.html for play."}
            yield {"type": "done"}

        tools_seen: list[str] = []
        stages: list[str] = []

        async def on_tool(name: str) -> None:
            tools_seen.append(name)

        async def on_stage(event: dict) -> None:
            stages.append(event["stage"])

        with patch.object(er, "run_agent_worker_events", fake_worker_events):
            ctx = await er.run_exhaustive_pipeline(
                app={},
                prompt="make me a snake game",
                instructions="build",
                work_dir="",
                profile="local",
                effort="exhaustive",
                specialist_id="coding",
                emit_stage=on_stage,
                on_tool=on_tool,
            )

        self.assertIn("game.html", ctx.result)
        self.assertIn("staff_crew", stages)
        self.assertIn("verify_review", stages)
        self.assertIn("deliver", stages)
        self.assertIn("fs.write_file", tools_seen)
        self.assertTrue(ctx.verified)  # ruff verifier ran (no workspace -> defensive pass)
        self.assertTrue(ctx.review_passed)

    async def test_worker_error_propagates_for_fallback(self):
        async def boom(app, **kwargs):  # noqa: ANN001, ANN003
            yield {"type": "error", "error": "tool blew up"}

        with patch.object(er, "run_agent_worker_events", boom):
            with self.assertRaises(RuntimeError):
                await er.run_exhaustive_pipeline(
                    app={},
                    prompt="build me a feature",
                    instructions="build",
                    work_dir="",
                    profile="local",
                    effort="exhaustive",
                    specialist_id="coding",
                )


if __name__ == "__main__":
    unittest.main()
