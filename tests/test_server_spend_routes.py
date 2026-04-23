"""Tests for thomas.server.routes.spend (cost tracking endpoints)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.cost_tracker import CostTracker
from thomas.server.app import create_app


class TestSpendRoutesLocal(AioHTTPTestCase):
    """Test spend/cost routes under local access mode."""

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._spend_path = Path(self._tmpdir.name) / "spend.jsonl"
        self._toml_path = Path(self._tmpdir.name) / "thomas.toml"
        self._toml_path.write_text("", encoding="utf-8")
        self._tracker = CostTracker(
            spend_path=self._spend_path,
            toml_path=self._toml_path,
        )

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

    # ── /api/spend/today ──

    async def test_spend_today_empty(self):
        with patch("thomas.server.routes.spend.get_cost_tracker", return_value=self._tracker):
            resp = await self.client.get("/api/spend/today")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("total_usd", body)
        self.assertIn("by_model", body)
        self.assertIn("call_count", body)
        self.assertIn("tokens", body)
        self.assertEqual(body["total_usd"], 0.0)

    async def test_spend_today_with_record(self):
        self._tracker.record(model="gpt-4o", provider="openai", prompt_tokens=100, completion_tokens=50)
        with patch("thomas.server.routes.spend.get_cost_tracker", return_value=self._tracker):
            resp = await self.client.get("/api/spend/today")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertGreater(body["total_usd"], 0)
        self.assertIn("gpt-4o", body["by_model"])
        self.assertEqual(body["call_count"], 1)

    # ── /api/spend/session ──

    async def test_spend_session(self):
        self._tracker.record(model="gpt-4o", provider="openai", prompt_tokens=10, completion_tokens=5)
        with patch("thomas.server.routes.spend.get_cost_tracker", return_value=self._tracker):
            resp = await self.client.get("/api/spend/session")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("total_usd", body)
        self.assertGreater(body["total_usd"], 0)
        self.assertIn("call_count", body)

    # ── POST /api/spend/session/reset ──

    async def test_spend_session_reset(self):
        self._tracker.record(model="gpt-4o", provider="openai", prompt_tokens=10, completion_tokens=5)
        with patch("thomas.server.routes.spend.get_cost_tracker", return_value=self._tracker):
            resp = await self.client.post("/api/spend/session/reset")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(self._tracker.session_usd(), 0.0)

    # ── /api/spend/history ──

    async def test_spend_history_default(self):
        with patch("thomas.server.routes.spend.get_cost_tracker", return_value=self._tracker):
            resp = await self.client.get("/api/spend/history")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 7)  # default 7 days
        for row in body:
            self.assertIn("date", row)
            self.assertIn("usd", row)

    async def test_spend_history_custom_days(self):
        with patch("thomas.server.routes.spend.get_cost_tracker", return_value=self._tracker):
            resp = await self.client.get("/api/spend/history?days=14")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(len(body), 14)

    # ── /api/spend/pricing ──

    async def test_spend_pricing(self):
        with patch("thomas.server.routes.spend.get_cost_tracker", return_value=self._tracker):
            resp = await self.client.get("/api/spend/pricing")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("pricing", body)
        self.assertIsInstance(body["pricing"], dict)

    # ── /api/spend/export.csv ──

    async def test_spend_export_csv(self):
        self._tracker.record(model="gpt-4o", provider="openai", prompt_tokens=10, completion_tokens=5)
        with patch("thomas.server.routes.spend.get_cost_tracker", return_value=self._tracker):
            resp = await self.client.get("/api/spend/export.csv?days=7")
        self.assertEqual(resp.status, 200)
        content_type = resp.headers.get("Content-Type", "")
        self.assertIn("text/csv", content_type)
        text = await resp.text()
        self.assertIn("date,usd", text)

    # ── /api/spend/stream (SSE) ──

    async def test_spend_stream_starts(self):
        with patch("thomas.server.routes.spend.get_cost_tracker", return_value=self._tracker):
            resp = await self.client.get("/api/spend/stream")
        # SSE endpoint starts streaming; we just verify status + content type
        self.assertEqual(resp.status, 200)
        content_type = resp.headers.get("Content-Type", "")
        self.assertIn("text/event-stream", content_type)

    async def test_runtime_profile(self):
        resp = await self.client.get("/api/runtime/profile")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("economy_level", body)
        self.assertIn("autonomy_level", body)

    async def test_runtime_matrix(self):
        resp = await self.client.get("/api/runtime/matrix")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("profiles", body)
        self.assertIsInstance(body["profiles"], list)


class TestSpendRoutesRemoteAuth(AioHTTPTestCase):
    """Verify spend routes require auth in remote mode."""

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

    async def test_spend_today_requires_auth(self):
        no_auth = await self.client.get("/api/spend/today")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/spend/today",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_spend_history_requires_auth(self):
        no_auth = await self.client.get("/api/spend/history")
        self.assertEqual(no_auth.status, 401)

    async def test_spend_session_reset_requires_auth(self):
        no_auth = await self.client.post("/api/spend/session/reset")
        self.assertEqual(no_auth.status, 401)


if __name__ == "__main__":
    unittest.main()
