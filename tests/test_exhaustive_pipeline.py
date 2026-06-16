"""Exhaustive pipeline orchestrator (Step 5)."""

from __future__ import annotations

import unittest

from thomas.marketplace.orchestrator.exhaustive_pipeline import MAX_REMEDIATIONS, ExhaustivePipeline


class TestExhaustivePipeline(unittest.IsolatedAsyncioTestCase):
    async def test_clear_task_runs_all_stages_in_order(self):
        seen: list[str] = []

        async def emit(event: dict) -> None:
            seen.append(event["stage"])

        pipe = ExhaustivePipeline(emit=emit)
        ctx = await pipe.run(
            "Add a logout button to the navbar that clears the session so that the user returns to the login page"
        )
        self.assertEqual(
            ctx.stages,
            ["task_manager", "staff_crew", "research_rubric", "crew_work", "verify_review", "deliver"],
        )
        self.assertEqual(seen, ctx.stages)
        self.assertNotIn("intent_review", ctx.stages)  # clear task -> gate skipped
        self.assertTrue(ctx.crew)
        self.assertTrue(ctx.result)
        self.assertTrue(ctx.verified and ctx.review_passed)

    async def test_ambiguous_task_triggers_intent_review(self):
        pipe = ExhaustivePipeline()
        ctx = await pipe.run("just fix it somehow")
        self.assertIn("intent_review", ctx.stages)

    async def test_unconfirmed_intent_aborts_before_staffing(self):
        async def deny(_ctx) -> bool:
            return False

        pipe = ExhaustivePipeline(intent_review_fn=deny)
        ctx = await pipe.run("just fix it somehow")
        self.assertEqual(ctx.aborted, "intent_not_confirmed")
        self.assertNotIn("staff_crew", ctx.stages)

    async def test_remediation_loop_runs_when_verify_fails_then_passes(self):
        verify_calls = {"n": 0}
        work_calls = {"n": 0}

        async def verify(_ctx) -> bool:
            verify_calls["n"] += 1
            return verify_calls["n"] >= 2  # fail first, pass second

        async def work(_ctx) -> str:
            work_calls["n"] += 1
            return "work"

        pipe = ExhaustivePipeline(verify_fn=verify, work_fn=work)
        ctx = await pipe.run("build me a feature")
        self.assertEqual(ctx.remediations, 1)
        self.assertEqual(work_calls["n"], 2)  # initial work + 1 remediation
        self.assertIn("remediation", ctx.stages)

    async def test_remediation_caps_at_max(self):
        async def always_fail(_ctx) -> bool:
            return False

        pipe = ExhaustivePipeline(verify_fn=always_fail)
        ctx = await pipe.run("build me a feature")
        self.assertEqual(ctx.remediations, MAX_REMEDIATIONS)
        self.assertFalse(ctx.verified)
        self.assertIn("deliver", ctx.stages)  # still delivers best-effort


if __name__ == "__main__":
    unittest.main()
