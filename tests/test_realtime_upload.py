import unittest
import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient

from thomas.realtime.routes import setup_realtime_routes
from thomas.realtime.config import RealtimeConfig
from thomas.realtime import keys


class TestRealtimeUpload(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        setup_realtime_routes(app)
        app[keys.CONFIG] = RealtimeConfig(enabled=True, uploads_dir="runtime/.thomas/uploads/realtime_test")
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_upload(self):
        data = b"hello"
        form = aiohttp.FormData()
        form.add_field("file", data, filename="a.txt", content_type="text/plain")
        resp = await self.client.post("/api/realtime/upload", data=form)
        self.assertEqual(resp.status, 200)
        obj = await resp.json()
        self.assertTrue(obj["ok"])
        self.assertIn("handle", obj)
        self.assertEqual(obj["name"], "a.txt")
        self.assertEqual(obj["mime"], "text/plain")
        self.assertEqual(obj["size"], len(data))
