import tempfile

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestServerToolsApi(AioHTTPTestCase):
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

    async def test_api_tools_returns_normalized_tool_payload(self):
        response = await self.client.get("/api/tools")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertIn("tools", payload)
        self.assertIn("count", payload)
        self.assertIsInstance(payload["tools"], list)
        self.assertEqual(payload["count"], len(payload["tools"]))
        self.assertGreater(len(payload["tools"]), 0)

        first_tool = payload["tools"][0]
        self.assertIn("id", first_tool)
        self.assertIn("name", first_tool)
        self.assertIn("description", first_tool)
        self.assertIn("category", first_tool)
        self.assertIn("status", first_tool)
        self.assertIn("params", first_tool)
        self.assertIsInstance(first_tool["params"], dict)
