from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.server.routes.observability import register_observability_routes


class TestServerObservabilityRoutes(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        register_observability_routes(app)
        return app

    async def test_api_events_rejects_invalid_query_params(self):
        bad_limit = await self.client.get("/api/events?limit=oops")
        self.assertEqual(bad_limit.status, 400)
        self.assertIn("invalid limit", await bad_limit.text())

        bad_minutes = await self.client.get("/api/events?minutes=oops")
        self.assertEqual(bad_minutes.status, 400)
        self.assertIn("invalid minutes", await bad_minutes.text())

    async def test_api_agents_activity_returns_presence_payload(self):
        from thomas.server.routes import observability as mod

        original = mod.agent_presence.collect_presence
        mod.agent_presence.collect_presence = lambda: {
            "success": True,
            "repo_root": "repo",
            "generated_at": "now",
            "active_count": 1,
            "agents": [{"agent_id": "Codex 1"}],
            "warnings": [],
            "conflicts": [],
        }
        try:
            response = await self.client.get("/api/agents/activity")
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertEqual(payload["active_count"], 1)
            self.assertEqual(payload["agents"][0]["agent_id"], "Codex 1")
        finally:
            mod.agent_presence.collect_presence = original

    async def test_api_task_bot_executions_returns_runtime_summary(self):
        from thomas.server.routes import observability as mod

        original = mod.task_bot_runtime.read_summary
        mod.task_bot_runtime.read_summary = lambda refresh=True: {
            "execution_count": 2,
            "active_count": 1,
            "executions": [{"execution_id": "exec-1", "task_id": "task-1"}],
        }
        try:
            response = await self.client.get("/api/task-bots/executions")
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertTrue(payload["success"])
            self.assertEqual(payload["task_bots"]["execution_count"], 2)
            self.assertEqual(payload["task_bots"]["executions"][0]["execution_id"], "exec-1")
        finally:
            mod.task_bot_runtime.read_summary = original

    async def test_api_metrics_includes_task_bot_counts(self):
        from thomas.server.routes import observability as mod

        original = mod.task_bot_runtime.read_summary
        mod.task_bot_runtime.read_summary = lambda refresh=True: {
            "active_count": 3,
            "stale_count": 1,
            "awaiting_proof_count": 2,
        }
        try:
            response = await self.client.get("/api/metrics")
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertEqual(payload["metrics"]["task_bot_active"], 3)
            self.assertEqual(payload["metrics"]["task_bot_stale"], 1)
            self.assertEqual(payload["metrics"]["task_bot_awaiting_proof"], 2)
        finally:
            mod.task_bot_runtime.read_summary = original
