"""Tests for thomas.server.routes.onboarding_aiohttp (telemetry, outcomes, gate)."""

import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestOnboardingRoutesLocal(AioHTTPTestCase):
    """Test onboarding routes under local access mode."""

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
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    # ── /api/onboarding/telemetry ──

    async def test_telemetry_accepts_event(self):
        resp = await self.client.post(
            "/api/onboarding/telemetry",
            json={"event": "step_completed", "payload": {"step": "welcome"}},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))

    async def test_telemetry_accepts_empty_body(self):
        resp = await self.client.post("/api/onboarding/telemetry", json={})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))

    async def test_telemetry_with_session_id_and_elapsed(self):
        resp = await self.client.post(
            "/api/onboarding/telemetry",
            json={
                "event": "profile_selected",
                "onboarding_session_id": "test-abc-123",
                "elapsed_ms": 4500,
                "payload": {"profile": "local"},
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))

    # ── /api/onboarding/outcomes ──

    async def test_outcomes_returns_report(self):
        resp = await self.client.get("/api/onboarding/outcomes")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        # Either ok=True with report or ok=False with error (if no data yet)
        self.assertIn("ok", body)

    async def test_outcomes_accepts_days_param(self):
        resp = await self.client.get("/api/onboarding/outcomes?days=30")
        self.assertEqual(resp.status, 200)

    # ── /api/onboarding/outcomes/gate ──

    async def test_outcomes_gate_returns_status(self):
        resp = await self.client.get("/api/onboarding/outcomes/gate")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("ok", body)

    async def test_outcomes_gate_accepts_custom_thresholds(self):
        resp = await self.client.get(
            "/api/onboarding/outcomes/gate"
            "?days=14&min_completion_rate=0.8&min_recovery_success_rate=0.7"
            "&max_median_time_to_ready_seconds=600"
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("ok", body)


class TestOnboardingRoutesRemoteAuth(AioHTTPTestCase):
    """Verify onboarding routes require auth in remote mode."""

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

    async def test_telemetry_requires_auth(self):
        no_auth = await self.client.post(
            "/api/onboarding/telemetry",
            json={"event": "test"},
        )
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.post(
            "/api/onboarding/telemetry",
            json={"event": "test"},
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_outcomes_requires_auth(self):
        no_auth = await self.client.get("/api/onboarding/outcomes")
        self.assertEqual(no_auth.status, 401)

    async def test_outcomes_gate_requires_auth(self):
        no_auth = await self.client.get("/api/onboarding/outcomes/gate")
        self.assertEqual(no_auth.status, 401)


if __name__ == "__main__":
    unittest.main()
