"""Tests for thomas.server.routes.setup_aiohttp (bootstrap, repair, diagnostics, local pull)."""

import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestSetupRoutesLocal(AioHTTPTestCase):
    """Test setup/bootstrap routes under local access mode."""

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
                "local": ModelConfig(
                    name="local",
                    model="llama3",
                    provider="ollama",
                    base_url="http://127.0.0.1:11434/v1",
                ),
                "cloud": ModelConfig(
                    name="cloud",
                    model="gpt-4",
                    provider="openai",
                    api_key="sk-test",
                ),
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    # ── /api/setup/bootstrap ──

    async def test_bootstrap_returns_system_info(self):
        resp = await self.client.get("/api/setup/bootstrap")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("system", body)
        self.assertIn("platform", body["system"])
        self.assertIn("python_version", body["system"])

    async def test_bootstrap_returns_tools(self):
        resp = await self.client.get("/api/setup/bootstrap")
        body = await resp.json()
        self.assertIn("tools", body)
        tools = body["tools"]
        for key in ("codex", "node", "npm", "ollama"):
            self.assertIn(key, tools)
            self.assertIn("installed", tools[key])

    async def test_bootstrap_returns_profiles(self):
        resp = await self.client.get("/api/setup/bootstrap")
        body = await resp.json()
        self.assertIn("profiles", body)
        profiles = body["profiles"]
        self.assertIn("default", profiles)
        self.assertIn("rows", profiles)
        self.assertIsInstance(profiles["rows"], list)
        self.assertGreaterEqual(len(profiles["rows"]), 2)
        # cloud profile should have a key
        cloud_row = next((r for r in profiles["rows"] if r["name"] == "cloud"), None)
        self.assertIsNotNone(cloud_row)
        self.assertTrue(cloud_row["has_key"])

    async def test_bootstrap_returns_quick_start(self):
        resp = await self.client.get("/api/setup/bootstrap")
        body = await resp.json()
        self.assertIn("quick_start", body)
        qs = body["quick_start"]
        self.assertIn("recommended_path", qs)
        self.assertIn(qs["recommended_path"], ("codex", "local", "cloud"))
        self.assertIn("reason", qs)
        self.assertTrue(len(qs["reason"]) > 5)

    # ── /api/setup/diagnostics ──

    async def test_diagnostics_returns_report(self):
        resp = await self.client.get("/api/setup/diagnostics")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("ok", body)
        self.assertIn("config", body)
        self.assertIn("runtime", body)
        self.assertIn("python_version", body["runtime"])
        self.assertIn("access_mode", body["runtime"])
        self.assertIn("next_actions", body)
        self.assertIsInstance(body["next_actions"], list)

    # ── /api/setup/repair ──

    async def test_repair_requires_post(self):
        resp = await self.client.get("/api/setup/repair")
        # Should be 405 Method Not Allowed (no GET registered)
        self.assertIn(resp.status, (404, 405))

    # ── /api/local/pull ──

    async def test_local_pull_missing_model_returns_400(self):
        resp = await self.client.post("/api/local/pull", json={})
        self.assertEqual(resp.status, 400)

    async def test_local_pull_with_model_starts_stream(self):
        """Pull with a model_id should start a streaming response (or fail connecting to Ollama)."""
        resp = await self.client.post(
            "/api/local/pull",
            json={"model_id": "llama3"},
        )
        # Will be 200 with NDJSON stream (may contain error if Ollama not running)
        self.assertEqual(resp.status, 200)
        content_type = resp.headers.get("Content-Type", "")
        self.assertIn("ndjson", content_type)

    async def test_local_background_status_returns_health_payload(self):
        resp = await self.client.get("/api/local/background")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("ok", body)
        self.assertTrue(bool(body["ok"]))
        self.assertIn("status", body)
        self.assertIn("health", body)
        self.assertIn("recent_reports", body)
        self.assertIn("task_catalog", body)

    async def test_local_background_control_updates_runtime_settings(self):
        resp = await self.client.post(
            "/api/local/background",
            json={"enabled": True, "min_gpu_headroom_pct": 44},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("updated_settings", body)
        updated = body["updated_settings"]
        self.assertEqual(bool(updated.get("local_background_agents_enabled")), True)
        self.assertEqual(int(updated.get("local_background_min_gpu_headroom_pct")), 44)

        prefs_resp = await self.client.get("/api/preferences")
        self.assertEqual(prefs_resp.status, 200)
        prefs = await prefs_resp.json()
        runtime = (prefs.get("advanced") or {}).get("runtime") or {}
        self.assertEqual(bool(runtime.get("local_background_agents_enabled")), True)
        self.assertEqual(int(runtime.get("local_background_min_gpu_headroom_pct")), 44)

    async def test_local_sync_returns_extended_probe_contract(self):
        resp = await self.client.post(
            "/api/local/sync",
            json={
                "model_ids": ["llama3"],
                "verify_only": True,
                "verify_inference": True,
                "verify_tooling": True,
            },
        )
        self.assertIn(resp.status, (200, 207))
        body = await resp.json()
        self.assertIn("verify_inference", body)
        self.assertIn("verify_tooling", body)
        self.assertIn("readiness", body)
        self.assertIn("results", body)
        self.assertGreaterEqual(len(body["results"]), 1)
        first = body["results"][0]
        self.assertIn("probe_ok", first)
        self.assertIn("probe", first)
        self.assertIn("repair_attempted", first)
        self.assertIn("repair_events_tail", first)

    async def test_local_sync_can_apply_recommended_runtime_settings(self):
        resp = await self.client.post(
            "/api/local/sync",
            json={
                "model_ids": ["llama3"],
                "verify_only": True,
                "apply_recommended_settings": True,
            },
        )
        self.assertIn(resp.status, (200, 207))
        body = await resp.json()
        self.assertIn("settings_applied", body)
        settings_applied = body["settings_applied"]
        self.assertIn("local_background_agents_enabled", settings_applied)
        self.assertIn("local_background_min_gpu_headroom_pct", settings_applied)

        prefs_resp = await self.client.get("/api/preferences")
        self.assertEqual(prefs_resp.status, 200)
        prefs = await prefs_resp.json()
        runtime = (prefs.get("advanced") or {}).get("runtime") or {}
        self.assertEqual(
            bool(runtime.get("local_background_agents_enabled")),
            bool(settings_applied.get("local_background_agents_enabled")),
        )
        self.assertEqual(
            int(runtime.get("local_background_min_gpu_headroom_pct")),
            int(settings_applied.get("local_background_min_gpu_headroom_pct")),
        )


class TestSetupRoutesRemoteAuth(AioHTTPTestCase):
    """Verify setup routes require auth in remote mode."""

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

    async def test_bootstrap_requires_auth(self):
        no_auth = await self.client.get("/api/setup/bootstrap")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/setup/bootstrap",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_diagnostics_requires_auth(self):
        no_auth = await self.client.get("/api/setup/diagnostics")
        self.assertEqual(no_auth.status, 401)

    async def test_local_pull_requires_auth(self):
        no_auth = await self.client.post(
            "/api/local/pull",
            json={"model_id": "llama3"},
        )
        self.assertEqual(no_auth.status, 401)


if __name__ == "__main__":
    unittest.main()
