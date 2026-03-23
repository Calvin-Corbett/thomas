"""Tests for thomas.server.routes.models_aiohttp (model/profile listing, version)."""

import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.app_keys import APP_RUNTIME_GUARD_STATE


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

    async def test_version_returns_runtime_guard(self):
        resp = await self.client.get("/api/version")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("version", body)
        self.assertIsInstance(body["version"], str)
        self.assertTrue(len(body["version"]) > 0)
        self.assertIn("runtime_guard", body)
        runtime_guard = body["runtime_guard"]
        self.assertIsInstance(runtime_guard, dict)
        self.assertIn("is_latest_code", runtime_guard)
        self.assertIn("state", runtime_guard)
        self.assertIn("checked_at_utc", runtime_guard)
        self.assertIn("reasons", runtime_guard)
        self.assertIn("alert_message", runtime_guard)

    async def test_version_runtime_guard_state_is_exposed(self):
        guard_state = self.app.get(APP_RUNTIME_GUARD_STATE)
        self.assertIsInstance(guard_state, dict)
        guard_state["status"] = {
            "checked_at_utc": "2026-02-26T00:00:00Z",
            "is_latest_code": False,
            "state": "stale",
            "reasons": ["git_head_changed_since_boot"],
            "alert_message": "Code changed after boot.",
        }
        guard_state["current"] = {
            "pid": 1234,
            "lock": {"pid": 5678, "port": 18899},
        }
        resp = await self.client.get("/api/version")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        runtime_guard = body.get("runtime_guard", {})
        self.assertEqual(runtime_guard.get("state"), "stale")
        self.assertFalse(runtime_guard.get("is_latest_code"))
        self.assertIn("git_head_changed_since_boot", runtime_guard.get("reasons", []))
        self.assertEqual(runtime_guard.get("lock_pid"), 5678)
        self.assertEqual(runtime_guard.get("lock_port"), 18899)


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
        body = await resp.json()
        self.assertIn("runtime_guard", body)

    async def test_capabilities_requires_auth(self):
        no_auth = await self.client.get("/api/models/capabilities")
        self.assertEqual(no_auth.status, 401)


if __name__ == "__main__":
    unittest.main()
