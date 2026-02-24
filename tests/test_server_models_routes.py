"""Tests for thomas.server.routes.models_aiohttp (model/profile listing, version)."""

import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestModelsRoutesLocal(AioHTTPTestCase):
    """Test model/profile routes under local access mode."""

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={
                "local": ModelConfig(name="local", model="llama3", provider="ollama"),
                "cloud": ModelConfig(name="cloud", model="gpt-4", provider="openai", api_key="sk-test"),
            },
            default_model="cloud",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_models_returns_profiles(self):
        resp = await self.client.get("/api/models")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["default"], "cloud")
        self.assertIsInstance(body["profiles"], list)
        names = [p["name"] for p in body["profiles"]]
        self.assertIn("local", names)
        self.assertIn("cloud", names)

    async def test_models_profile_fields(self):
        resp = await self.client.get("/api/models")
        body = await resp.json()
        cloud = next(p for p in body["profiles"] if p["name"] == "cloud")
        self.assertEqual(cloud["provider"], "openai")
        self.assertEqual(cloud["model"], "gpt-4")
        self.assertTrue(cloud["has_api_key"])

    async def test_models_capabilities(self):
        resp = await self.client.get("/api/models/capabilities")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("profiles", body)
        self.assertIn("cloud", body["profiles"])
        self.assertIn("local", body["profiles"])

    async def test_profile_unknown_returns_404(self):
        resp = await self.client.get("/api/models/nonexistent/handshake")
        self.assertEqual(resp.status, 404)

    async def test_profile_validate_unknown_returns_404(self):
        resp = await self.client.get("/api/models/nonexistent/validate")
        self.assertEqual(resp.status, 404)

    async def test_profile_ids_unknown_returns_404(self):
        resp = await self.client.get("/api/models/nonexistent/ids")
        self.assertEqual(resp.status, 404)

    async def test_version_returns_string(self):
        resp = await self.client.get("/api/version")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("version", body)
        self.assertIsInstance(body["version"], str)
        self.assertTrue(len(body["version"]) > 0)


class TestModelsRoutesRemoteAuth(AioHTTPTestCase):
    """Verify model routes require auth in remote mode."""

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="remote", api_token="test-token"),
        )
        return create_app(cfg)

    async def test_models_requires_auth_in_remote(self):
        no_auth = await self.client.get("/api/models")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/models",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_version_unauthenticated_ok_by_default(self):
        # Version endpoint allows unauthenticated access by default
        resp = await self.client.get("/api/version")
        self.assertEqual(resp.status, 200)

    async def test_capabilities_requires_auth(self):
        no_auth = await self.client.get("/api/models/capabilities")
        self.assertEqual(no_auth.status, 401)


if __name__ == "__main__":
    unittest.main()
