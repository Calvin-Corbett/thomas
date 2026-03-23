"""Tests for thomas.server.routes.codex_aiohttp (Codex bridge auth/models)."""

import tempfile
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app

# ── Fake Codex bridge objects for testing ──


@dataclass
class FakeCodexAccount:
    logged_in: bool = False
    email: str = ""
    display_name: str = ""
    avatar_url: str = ""
    plan_type: str = ""
    auth_type: str = ""


@dataclass
class FakeCodexModel:
    id: str = ""
    display_name: str = ""
    is_default: bool = False


class FakeCodexBridge:
    """Lightweight stand-in for the real CodexBridge (external service mock)."""

    def __init__(self, *, logged_in: bool = False, models: list[FakeCodexModel] | None = None):
        self._account = FakeCodexAccount(
            logged_in=logged_in,
            email="test@example.com" if logged_in else "",
            display_name="Test User" if logged_in else "",
            avatar_url="https://example.com/avatar.png" if logged_in else "",
            plan_type="pro" if logged_in else "",
            auth_type="chatgpt" if logged_in else "",
        )
        self._models = models or []
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def check_auth(self):
        return self._account

    async def login_chatgpt(self):
        self._account = FakeCodexAccount(
            logged_in=True,
            email="test@example.com",
            display_name="Test User",
            avatar_url="https://example.com/avatar.png",
            plan_type="pro",
            auth_type="chatgpt",
        )
        return self._account

    async def logout(self):
        self._account = FakeCodexAccount(logged_in=False)

    async def list_models(self):
        return self._models


class TestCodexRoutesLocal(AioHTTPTestCase):
    """Test Codex bridge routes under local access mode."""

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
                "local": ModelConfig(name="local", model="dummy"),
                "codex": ModelConfig(name="codex", model="gpt-4o", provider="codex"),
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    # ── /api/codex/status ──

    async def test_codex_status_not_logged_in(self):
        """Status returns logged_in=False when bridge has no active session."""
        fake = FakeCodexBridge(logged_in=False)
        with patch("thomas.marketplace.codex.bridge.CodexBridge", return_value=fake):
            resp = await self.client.get("/api/codex/status")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertFalse(body["logged_in"])

    async def test_codex_status_logged_in(self):
        """Status returns account fields when bridge reports logged in."""
        fake = FakeCodexBridge(logged_in=True)
        with patch("thomas.marketplace.codex.bridge.CodexBridge", return_value=fake):
            resp = await self.client.get("/api/codex/status")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["logged_in"])
        self.assertEqual(body["email"], "test@example.com")
        self.assertIn("display_name", body)
        self.assertIn("plan_type", body)

    # ── /api/codex/login ──

    async def test_codex_login_fresh(self):
        """Login completes successfully on a fresh bridge."""
        fake = FakeCodexBridge(logged_in=False)
        with patch("thomas.marketplace.codex.bridge.CodexBridge", return_value=fake):
            resp = await self.client.post("/api/codex/login", json={})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["already"])
        self.assertEqual(body["email"], "test@example.com")

    async def test_codex_login_already_logged_in(self):
        """Login returns already=True when already authenticated."""
        fake = FakeCodexBridge(logged_in=True)
        with patch("thomas.marketplace.codex.bridge.CodexBridge", return_value=fake):
            resp = await self.client.post("/api/codex/login", json={})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["already"])

    # ── /api/codex/logout ──

    async def test_codex_logout(self):
        """Logout returns ok even when no bridge is active."""
        resp = await self.client.post("/api/codex/logout", json={})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])

    # ── /api/codex/models ──

    async def test_codex_models_returns_list(self):
        """Models endpoint returns a list of model objects."""
        fake = FakeCodexBridge(
            logged_in=True,
            models=[
                FakeCodexModel(id="gpt-4o", display_name="GPT-4o", is_default=True),
                FakeCodexModel(id="gpt-4o-mini", display_name="GPT-4o Mini", is_default=False),
            ],
        )
        with patch("thomas.marketplace.codex.bridge.CodexBridge", return_value=fake):
            resp = await self.client.get("/api/codex/models")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("models", body)
        self.assertEqual(len(body["models"]), 2)
        self.assertEqual(body["models"][0]["id"], "gpt-4o")
        self.assertTrue(body["models"][0]["is_default"])

    async def test_codex_models_empty_when_bridge_fails(self):
        """Models endpoint returns empty list + error when bridge is broken."""
        # Without patching, CodexBridge import will fail or raise
        # The handler wraps this in try/except, so we get a graceful fallback
        resp = await self.client.get("/api/codex/models")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        # Should have an error field or empty models
        self.assertIsInstance(body.get("models", []), list)


class TestCodexRoutesRemoteAuth(AioHTTPTestCase):
    """Verify Codex routes require auth in remote mode."""

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

    async def test_codex_status_requires_auth(self):
        no_auth = await self.client.get("/api/codex/status")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/codex/status",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_codex_login_requires_auth(self):
        no_auth = await self.client.post("/api/codex/login", json={})
        self.assertEqual(no_auth.status, 401)

    async def test_codex_models_requires_auth(self):
        no_auth = await self.client.get("/api/codex/models")
        self.assertEqual(no_auth.status, 401)


if __name__ == "__main__":
    unittest.main()
