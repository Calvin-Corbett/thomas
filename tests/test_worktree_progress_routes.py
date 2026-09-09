"""HTTP-layer tests for the worktree-progress routes (CAP-139).

Acceptance line: "Add per-worktree status plus task-graph timing and cost."

Proven here through the HTTP layer (aiohttp test client, no network, fixed
clock, no temp state on disk):
  * a single snapshot response carries all three sections -- per-worktree
    status, task-graph timing, and the cost rollup;
  * events ingested over POST drive those sections (active / idle / done,
    current node, elapsed);
  * a still-running node reports elapsed-so-far with ``running: true``;
  * the critical path is reported as an explicit node list + total duration so
    the panel can visually distinguish it;
  * bad input is 4xx (400 malformed, 409 lifecycle conflict) -- never a 500.
"""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.observability.worktree_progress import ProgressAggregator
from thomas.server.routes.worktree_progress_routes import (
    register_worktree_progress_routes,
    reset_progress_aggregator,
    set_progress_aggregator,
)

SNAPSHOT = "/api/worktree-progress/snapshot"
EVENTS = "/api/worktree-progress/events"
RESET = "/api/worktree-progress/reset"


class TestWorktreeProgressRoutes(AioHTTPTestCase):
    async def get_application(self):
        # Deterministic clock: every event/snapshot in these tests passes an
        # explicit ``at`` / ``now``, so the clock never leaks wall time.
        set_progress_aggregator(ProgressAggregator(clock=lambda: 0.0))
        app = web.Application()
        register_worktree_progress_routes(app, config=None)
        return app

    async def tearDownAsync(self) -> None:
        set_progress_aggregator(None)
        await super().tearDownAsync()

    # -- helpers ---------------------------------------------------------
    async def _post_event(self, payload: dict, *, expect: int = 200) -> dict:
        resp = await self.client.post(EVENTS, json=payload)
        self.assertEqual(resp.status, expect, await resp.text())
        return await resp.json()

    async def _snapshot(self, now: float) -> dict:
        resp = await self.client.get(f"{SNAPSHOT}?now={now}")
        self.assertEqual(resp.status, 200, await resp.text())
        body = await resp.json()
        self.assertTrue(body["ok"])
        return body["snapshot"]

    async def _seed_graph(self) -> None:
        """a -> b -> d, a -> c -> d; d is still running at now=50."""

        await self._post_event({"event": "node_started", "worktree_id": "wt-1", "node_id": "a", "at": 0})
        await self._post_event({"event": "node_finished", "node_id": "a", "at": 10, "tokens": 100, "cost": 0.5})
        await self._post_event(
            {"event": "node_started", "worktree_id": "wt-1", "node_id": "b", "depends_on": ["a"], "at": 10}
        )
        await self._post_event({"event": "node_finished", "node_id": "b", "at": 40, "tokens": 300, "cost": 1.5})
        await self._post_event(
            {"event": "node_started", "worktree_id": "wt-2", "node_id": "c", "depends_on": ["a"], "at": 10}
        )
        await self._post_event({"event": "node_finished", "node_id": "c", "at": 15, "tokens": 50, "cost": 0.25})
        await self._post_event(
            {"event": "node_started", "worktree_id": "wt-1", "node_id": "d", "depends_on": ["b", "c"], "at": 40}
        )
        await self._post_event({"event": "register_worktree", "worktree_id": "wt-3"})

    # -- acceptance: all three sections in one snapshot -------------------
    async def test_snapshot_carries_status_timing_and_cost_sections(self):
        await self._seed_graph()
        snap = await self._snapshot(50)

        # (1) per-worktree status
        self.assertEqual({w["worktree_id"] for w in snap["worktrees"]}, {"wt-1", "wt-2", "wt-3"})
        # (2) task-graph timing
        self.assertEqual({t["node_id"] for t in snap["node_timings"]}, {"a", "b", "c", "d"})
        self.assertIn("critical_path", snap)
        # (3) cost rollup
        self.assertIn("per_worktree", snap["cost"])
        self.assertIn("total", snap["cost"])

    async def test_empty_snapshot_still_has_all_three_sections(self):
        snap = await self._snapshot(0)
        self.assertEqual(snap["worktrees"], [])
        self.assertEqual(snap["node_timings"], [])
        self.assertEqual(snap["critical_path"], {"nodes": [], "duration_s": 0.0})
        self.assertEqual(snap["cost"]["total"], 0.0)

    # -- per-worktree status ---------------------------------------------
    async def test_worktree_states_active_idle_done(self):
        await self._seed_graph()
        snap = await self._snapshot(50)
        by_id = {w["worktree_id"]: w for w in snap["worktrees"]}

        self.assertEqual(by_id["wt-1"]["state"], "active")
        self.assertEqual(by_id["wt-1"]["current_node"], "d")
        self.assertEqual(by_id["wt-1"]["running_nodes"], ["d"])

        self.assertEqual(by_id["wt-2"]["state"], "done")
        self.assertEqual(by_id["wt-2"]["node_count"], 1)

        self.assertEqual(by_id["wt-3"]["state"], "idle")
        self.assertIsNone(by_id["wt-3"]["current_node"])
        self.assertEqual(by_id["wt-3"]["node_count"], 0)

    async def test_running_node_reports_elapsed_so_far_and_grows(self):
        await self._post_event({"event": "node_started", "worktree_id": "wt-1", "node_id": "solo", "at": 100})

        early = await self._snapshot(105)
        late = await self._snapshot(130)

        early_timing = next(t for t in early["node_timings"] if t["node_id"] == "solo")
        late_timing = next(t for t in late["node_timings"] if t["node_id"] == "solo")
        self.assertTrue(early_timing["running"])
        self.assertIsNone(early_timing["finished_at"])
        self.assertEqual(early_timing["duration_s"], 5.0)
        self.assertEqual(late_timing["duration_s"], 30.0)

        self.assertEqual(early["worktrees"][0]["state"], "active")
        self.assertEqual(early["worktrees"][0]["elapsed_s"], 5.0)
        self.assertEqual(late["worktrees"][0]["elapsed_s"], 30.0)

    # -- task-graph timing + critical path --------------------------------
    async def test_node_timings_and_critical_path(self):
        await self._seed_graph()
        snap = await self._snapshot(50)

        durations = {t["node_id"]: t["duration_s"] for t in snap["node_timings"]}
        self.assertEqual(durations["a"], 10.0)
        self.assertEqual(durations["b"], 30.0)
        self.assertEqual(durations["c"], 5.0)
        self.assertEqual(durations["d"], 10.0)  # elapsed-so-far, still running

        # Longest path is a -> b -> d (10 + 30 + 10), not the c branch.
        self.assertEqual(snap["critical_path"]["nodes"], ["a", "b", "d"])
        self.assertEqual(snap["critical_path"]["duration_s"], 50.0)
        # Convenience mirror the panel uses to highlight rows.
        self.assertEqual(snap["critical_path_nodes"], ["a", "b", "d"])
        self.assertNotIn("c", snap["critical_path_nodes"])

    # -- cost rollup ------------------------------------------------------
    async def test_cost_rolls_up_per_worktree_and_total(self):
        await self._seed_graph()
        snap = await self._snapshot(50)
        cost = snap["cost"]

        self.assertEqual(cost["per_node"]["b"], 1.5)
        self.assertEqual(cost["per_node"]["d"], 0.0)  # unfinished node has no cost yet
        self.assertEqual(cost["per_worktree"]["wt-1"], 2.0)
        self.assertEqual(cost["per_worktree"]["wt-2"], 0.25)
        self.assertEqual(cost["per_worktree"]["wt-3"], 0.0)
        self.assertEqual(cost["total"], 2.25)
        self.assertEqual(cost["tokens_per_worktree"]["wt-1"], 400)
        self.assertEqual(cost["tokens_total"], 450)

    # -- reset ------------------------------------------------------------
    async def test_reset_clears_all_state(self):
        await self._seed_graph()
        resp = await self.client.post(RESET, json={})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["snapshot"]["worktrees"], [])
        self.assertEqual(body["snapshot"]["node_timings"], [])

        snap = await self._snapshot(50)
        self.assertEqual(snap["cost"]["total"], 0.0)

    # -- input validation: 4xx, never 500 ---------------------------------
    async def test_non_object_body_is_400(self):
        resp = await self.client.post(EVENTS, json=["not", "an", "object"])
        self.assertEqual(resp.status, 400)
        self.assertEqual((await resp.json())["code"], "invalid_body")

    async def test_malformed_json_is_400(self):
        resp = await self.client.post(EVENTS, data="{not json", headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status, 400)
        self.assertEqual((await resp.json())["code"], "invalid_json")

    async def test_unknown_event_is_400(self):
        resp = await self.client.post(EVENTS, json={"event": "node_exploded", "node_id": "a"})
        self.assertEqual(resp.status, 400)
        self.assertEqual((await resp.json())["code"], "unknown_event")

    async def test_missing_fields_are_400(self):
        missing_node = await self.client.post(EVENTS, json={"event": "node_started", "worktree_id": "wt-1"})
        self.assertEqual(missing_node.status, 400)
        missing_wt = await self.client.post(EVENTS, json={"event": "node_started", "node_id": "a"})
        self.assertEqual(missing_wt.status, 400)
        blank = await self.client.post(EVENTS, json={"event": "register_worktree", "worktree_id": "   "})
        self.assertEqual(blank.status, 400)

    async def test_non_numeric_fields_are_400(self):
        bad_at = await self.client.post(
            EVENTS, json={"event": "node_started", "worktree_id": "wt-1", "node_id": "a", "at": "soon"}
        )
        self.assertEqual(bad_at.status, 400)
        await self._post_event({"event": "node_started", "worktree_id": "wt-1", "node_id": "a", "at": 0})
        bad_cost = await self.client.post(
            EVENTS, json={"event": "node_finished", "node_id": "a", "at": 1, "cost": {"usd": 1}}
        )
        self.assertEqual(bad_cost.status, 400)
        bad_deps = await self.client.post(
            EVENTS, json={"event": "node_started", "worktree_id": "wt-1", "node_id": "z", "depends_on": "a"}
        )
        self.assertEqual(bad_deps.status, 400)

    async def test_bad_now_query_is_400(self):
        resp = await self.client.get(f"{SNAPSHOT}?now=yesterday")
        self.assertEqual(resp.status, 400)
        self.assertEqual((await resp.json())["code"], "invalid_query")

    async def test_lifecycle_conflicts_are_409_not_500(self):
        await self._post_event({"event": "node_started", "worktree_id": "wt-1", "node_id": "a", "at": 0})

        duplicate = await self.client.post(
            EVENTS, json={"event": "node_started", "worktree_id": "wt-1", "node_id": "a", "at": 5}
        )
        self.assertEqual(duplicate.status, 409)
        self.assertEqual((await duplicate.json())["code"], "node_conflict")

        unknown = await self.client.post(EVENTS, json={"event": "node_finished", "node_id": "ghost", "at": 5})
        self.assertEqual(unknown.status, 409)

        backwards = await self.client.post(EVENTS, json={"event": "node_finished", "node_id": "a", "at": -10})
        self.assertEqual(backwards.status, 409)

    # -- module singleton --------------------------------------------------
    async def test_reset_helper_returns_fresh_aggregator(self):
        await self._post_event({"event": "node_started", "worktree_id": "wt-1", "node_id": "a", "at": 0})
        fresh = reset_progress_aggregator()
        self.assertEqual(fresh.worktree_ids(), [])
        snap = await self._snapshot(1)
        self.assertEqual(snap["worktrees"], [])
