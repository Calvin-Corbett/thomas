import os
import tempfile
import unittest
from datetime import datetime, timezone

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.autonomy.api import register_autonomy_routes
from thomas.autonomy.engine import AutonomyEngine
from thomas.autonomy.policy import AutonomyPolicy
from thomas.autonomy.store import AutonomyStore


class TestAutonomyAPI(AioHTTPTestCase):
    async def get_application(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "autonomy.sqlite3")
        store = AutonomyStore(self.db_path)
        policy = AutonomyPolicy()
        engine = AutonomyEngine(store=store, policy=policy)
        app = web.Application()
        register_autonomy_routes(app, engine=engine, store=store, policy=policy, api_token=None)

        # start engine in app lifecycle
        async def on_startup(app):
            await engine.start()

        async def on_cleanup(app):
            await engine.stop()
            store.close()
            self.tmpdir.cleanup()

        app.on_startup.append(on_startup)
        app.on_cleanup.append(on_cleanup)
        return app

    async def test_create_and_list(self):
        payload = {
            "name": "r",
            "kind": "reminder",
            "payload": {"text": "hi"},
            "risk_class": "low",
            "run_at": datetime.now(timezone.utc).isoformat(),
        }
        resp = await self.client.post("/api/autonomy/jobs", json=payload)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("job", data)
        self.assertIn("id", data["job"])

        resp2 = await self.client.get("/api/autonomy/jobs?limit=10")
        self.assertEqual(resp2.status, 200)
        data2 = await resp2.json()
        self.assertIn("jobs", data2)
        self.assertTrue(len(data2["jobs"]) >= 1)


if __name__ == "__main__":
    unittest.main()
