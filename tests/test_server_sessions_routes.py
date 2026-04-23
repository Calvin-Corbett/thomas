"""Tests for thomas.server.routes.sessions_aiohttp (session new, fork, import)."""

import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestSessionsRoutesLocal(AioHTTPTestCase):
    """Test session lifecycle routes under local access mode."""

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
                "cloud": ModelConfig(name="cloud", model="gpt-4", provider="openai"),
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    # ── session/new ──

    async def test_session_new_returns_session_id(self):
        resp = await self.client.post("/api/session/new", json={})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("session_id", body)
        self.assertIsInstance(body["session_id"], str)
        self.assertTrue(len(body["session_id"]) > 8)

    async def test_session_new_creates_unique_ids(self):
        resp1 = await self.client.post("/api/session/new", json={})
        resp2 = await self.client.post("/api/session/new", json={})
        body1 = await resp1.json()
        body2 = await resp2.json()
        self.assertNotEqual(body1["session_id"], body2["session_id"])

    # ── session/fork ──

    async def test_session_fork_clones_session(self):
        # Create a session first
        new_resp = await self.client.post("/api/session/new", json={})
        src_sid = (await new_resp.json())["session_id"]

        # Fork it
        fork_resp = await self.client.post(
            "/api/session/fork",
            json={"session_id": src_sid},
        )
        self.assertEqual(fork_resp.status, 200)
        fork_body = await fork_resp.json()
        self.assertIn("session_id", fork_body)
        self.assertIn("forked_from", fork_body)
        self.assertEqual(fork_body["forked_from"], src_sid)
        self.assertNotEqual(fork_body["session_id"], src_sid)

    async def test_session_fork_invalid_id_returns_400(self):
        resp = await self.client.post(
            "/api/session/fork",
            json={"session_id": "nonexistent-session-id"},
        )
        self.assertEqual(resp.status, 400)

    async def test_session_fork_missing_id_returns_400(self):
        resp = await self.client.post("/api/session/fork", json={})
        self.assertEqual(resp.status, 400)

    # ── session/import ──

    async def test_session_import_basic(self):
        resp = await self.client.post(
            "/api/session/import",
            json={
                "profile": "local",
                "conversation": [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there"},
                ],
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("session_id", body)
        self.assertTrue(len(body["session_id"]) > 8)

    async def test_session_import_unknown_profile_falls_back(self):
        """The v0.11.62 fix: unknown profile falls back instead of 400."""
        resp = await self.client.post(
            "/api/session/import",
            json={
                "profile": "totally-bogus-profile",
                "conversation": [{"role": "user", "content": "test"}],
            },
        )
        # Should gracefully fall back to default, not error
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("session_id", body)

    async def test_session_import_bad_conversation_type_returns_400(self):
        resp = await self.client.post(
            "/api/session/import",
            json={"profile": "local", "conversation": "not a list"},
        )
        self.assertEqual(resp.status, 400)

    async def test_session_import_conversation_too_long_returns_400(self):
        # Over the 250 message limit
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(260)]
        resp = await self.client.post(
            "/api/session/import",
            json={"profile": "local", "conversation": msgs},
        )
        self.assertEqual(resp.status, 400)

    async def test_session_import_empty_conversation_ok(self):
        resp = await self.client.post(
            "/api/session/import",
            json={"profile": "local", "conversation": []},
        )
        self.assertEqual(resp.status, 200)

    async def test_session_import_filters_invalid_roles(self):
        resp = await self.client.post(
            "/api/session/import",
            json={
                "profile": "local",
                "conversation": [
                    {"role": "system", "content": "sneaky"},
                    {"role": "user", "content": "legit"},
                    {"role": "tool", "content": "also sneaky"},
                ],
            },
        )
        self.assertEqual(resp.status, 200)


class TestSessionsRoutesRemoteAuth(AioHTTPTestCase):
    """Verify session routes require auth in remote mode."""

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

    async def test_session_new_requires_auth(self):
        no_auth = await self.client.post("/api/session/new", json={})
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.post(
            "/api/session/new",
            json={},
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_session_import_requires_auth(self):
        no_auth = await self.client.post(
            "/api/session/import",
            json={"profile": "local", "conversation": []},
        )
        self.assertEqual(no_auth.status, 401)


if __name__ == "__main__":
    unittest.main()
