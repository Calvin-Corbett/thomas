import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server.app import create_app


class TestServerMemoryContradictionsAPI(AioHTTPTestCase):
    async def get_application(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=str(Path(self.tmpdir.name) / "runtime")),
        )
        return create_app(cfg)

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        self.tmpdir.cleanup()

    async def test_list_and_resolve_contradictions(self):
        # Create a contradiction through profile-hint updates.
        pin1 = await self.client.post("/api/memory/pins", json={"key": "user.name", "text": "Calvin"})
        self.assertEqual(pin1.status, 200)
        pin2 = await self.client.post("/api/memory/pins", json={"key": "user.name", "text": "Kevin"})
        self.assertEqual(pin2.status, 200)

        resp = await self.client.get("/api/memory/contradictions?only_open=1&limit=20")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("ok"))
        rows = data.get("contradictions") or []
        self.assertGreaterEqual(len(rows), 1)
        cid = int(rows[0]["id"])

        resp2 = await self.client.post(
            f"/api/memory/contradictions/{cid}/resolve",
            json={"resolved": True},
        )
        self.assertEqual(resp2.status, 200)
        data2 = await resp2.json()
        self.assertTrue(data2.get("ok"))
        self.assertEqual(int(data2.get("id", 0)), cid)
        self.assertTrue(bool(data2.get("resolved")))

        resp3 = await self.client.get("/api/memory/contradictions?only_open=1&limit=50")
        self.assertEqual(resp3.status, 200)
        data3 = await resp3.json()
        open_ids = {int(r["id"]) for r in (data3.get("contradictions") or [])}
        self.assertNotIn(cid, open_ids)

    async def test_contradiction_review_routes(self):
        pin1 = await self.client.post("/api/memory/pins", json={"key": "user.city", "text": "Miami"})
        self.assertEqual(pin1.status, 200)
        pin2 = await self.client.post("/api/memory/pins", json={"key": "user.city", "text": "Orlando"})
        self.assertEqual(pin2.status, 200)

        list_resp = await self.client.get("/api/memory/contradictions/review?status=pending&limit=20")
        self.assertEqual(list_resp.status, 200)
        list_data = await list_resp.json()
        self.assertTrue(list_data.get("ok"))
        rows = list_data.get("contradictions") or []
        self.assertGreaterEqual(len(rows), 1)
        cid = int(rows[0]["id"])

        decide_resp = await self.client.post(
            f"/api/memory/contradictions/{cid}/review",
            json={"decision": "approve", "actor": "test", "reason": "verified"},
        )
        self.assertEqual(decide_resp.status, 200)
        decide_data = await decide_resp.json()
        self.assertTrue(decide_data.get("ok"))
        self.assertEqual(int(decide_data.get("id", 0)), cid)

        open_resp = await self.client.get("/api/memory/contradictions?only_open=1&limit=20")
        self.assertEqual(open_resp.status, 200)
        open_data = await open_resp.json()
        open_ids = {int(r["id"]) for r in (open_data.get("contradictions") or [])}
        self.assertNotIn(cid, open_ids)

    async def test_curator_approval_queue_routes(self):
        list_resp = await self.client.get("/api/memory/curator/approvals?status=pending&limit=20")
        self.assertEqual(list_resp.status, 200)
        list_data = await list_resp.json()
        self.assertTrue(list_data.get("ok"))
        rows = list_data.get("approvals") or []
        if rows:
            aid = int(rows[0]["id"])
            decide_resp = await self.client.post(
                f"/api/memory/curator/approvals/{aid}/decision",
                json={"approve": True, "actor": "test"},
            )
            self.assertEqual(decide_resp.status, 200)
            decide_data = await decide_resp.json()
            self.assertTrue(decide_data.get("ok"))
        else:
            not_found = await self.client.post(
                "/api/memory/curator/approvals/999999/decision",
                json={"approve": True, "actor": "test"},
            )
            self.assertEqual(not_found.status, 404)

    async def test_loopback_route_rejects_cross_origin_browser_requests(self):
        resp = await self.client.get(
            "/api/memory/contradictions?only_open=1&limit=5",
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(resp.status, 403)

    async def test_loopback_route_accepts_same_origin_browser_requests(self):
        base = self.client.make_url("/")
        origin = f"{base.scheme}://{base.host}:{base.port}"
        resp = await self.client.get(
            "/api/memory/contradictions?only_open=1&limit=5",
            headers={"Origin": origin},
        )
        self.assertEqual(resp.status, 200)

    async def test_loopback_route_accepts_android_emulator_local_origin_alias(self):
        base = self.client.make_url("/")
        origin = f"{base.scheme}://10.0.2.2:{base.port}"
        resp = await self.client.get(
            "/api/memory/contradictions?only_open=1&limit=5",
            headers={"Origin": origin},
        )
        self.assertEqual(resp.status, 200)

    async def test_json_routes_require_application_json_content_type(self):
        resp = await self.client.post(
            "/api/memory/pins",
            data='{"key":"user.name","text":"Calvin"}',
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(resp.status, 415)


if __name__ == "__main__":
    unittest.main()
