"""The Agents workspace as a row: its page and its vitals answer when it is on and are gone when it is off."""

import tempfile

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestAgentsRow(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_with_the_row_on_the_page_and_the_vitals_answer(self):
        page = await self.client.get("/agents")
        self.assertEqual(page.status, 200)
        self.assertIn("text/html", page.headers["Content-Type"])
        self.assertEqual((await self.client.get("/agents/")).status, 200)

        vitals = await self.client.get("/api/agents/vitals")
        self.assertEqual(vitals.status, 200)
        body = await vitals.json()
        self.assertTrue({"interval_s", "cpu", "memory", "latest"} <= set(body))

    async def test_with_the_row_off_both_routes_are_gone_and_back_when_it_is_turned_on(self):
        off = await self.client.post("/api/plugins/thomas/agents/off")
        self.assertEqual(off.status, 200, await off.text())
        self.assertEqual((await self.client.get("/agents")).status, 404)
        self.assertEqual((await self.client.get("/api/agents/vitals")).status, 404)

        on = await self.client.post("/api/plugins/thomas/agents/on")
        self.assertEqual(on.status, 200, await on.text())
        self.assertEqual((await self.client.get("/agents")).status, 200)
        self.assertEqual((await self.client.get("/api/agents/vitals")).status, 200)
