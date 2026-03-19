import json
import os
import tempfile
import unittest

from aiohttp import web

from thomas.autonomy.store import AutonomyStore
from thomas.server.routes.mission_tasks import build_mission_task_handlers


class _CreateRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class TestServerMissionEvolve(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = AutonomyStore(os.path.join(self.tmpdir.name, "autonomy.sqlite3"))

    async def asyncTearDown(self):
        self.store.close()
        self.tmpdir.cleanup()

    async def test_mission_job_create_accepts_evolve_session(self):
        app = web.Application()

        async def require_store(auto_enable=False):
            return self.store

        woke = {"called": False}

        def wake_engine():
            woke["called"] = True

        _, create_handler, *_ = build_mission_task_handlers(app, require_store, wake_engine)
        resp = await create_handler(
            _CreateRequest(
                {
                    "kind": "evolve_session",
                    "name": "Evolve Thomas",
                    "goal": "Improve web polish",
                    "profile": "local",
                }
            )
        )
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.text)
        self.assertIs(payload.get("ok"), True)
        job = payload.get("job") or {}
        self.assertEqual(str(job.get("kind") or ""), "evolve_session")
        self.assertEqual(str((job.get("payload") or {}).get("goal") or ""), "Improve web polish")
        self.assertEqual(str((job.get("payload") or {}).get("profile") or ""), "local")
        self.assertIs(woke["called"], True)
