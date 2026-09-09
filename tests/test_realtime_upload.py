import unittest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.marketplace.realtime import keys
from thomas.marketplace.realtime.config import RealtimeConfig
from thomas.marketplace.realtime.routes import setup_realtime_routes


def _require_bearer_token(request: web.Request) -> None:
    if request.headers.get("Authorization") != "Bearer test-token":
        raise web.HTTPUnauthorized(text="missing api token")


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


class TestRealtimeUploadAuth(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        setup_realtime_routes(app, require_api_access=_require_bearer_token)
        app[keys.CONFIG] = RealtimeConfig(enabled=True, uploads_dir="runtime/.thomas/uploads/realtime_test")
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_upload_requires_token(self):
        form = aiohttp.FormData()
        form.add_field("file", b"x", filename="x.txt", content_type="text/plain")
        resp = await self.client.post("/api/realtime/upload", data=form)
        self.assertEqual(resp.status, 401)

    async def test_upload_allows_authorized_client(self):
        form = aiohttp.FormData()
        form.add_field("file", b"x", filename="x.txt", content_type="text/plain")
        resp = await self.client.post(
            "/api/realtime/upload",
            data=form,
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(resp.status, 200)
