"""Tests for thomas.server.routes.search (FTS5 conversation search API)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.search_history import ConversationSearch
from thomas.server.app import create_app


class TestSearchRoutesLocal(AioHTTPTestCase):
    """Test search routes under local access mode."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._search_db = Path(self._tmpdir.name) / "test_search.db"
        self._search = ConversationSearch(db_path=self._search_db)
        super().setUp()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            try:
                self._search.close()
            except Exception:
                pass
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    # ── GET /api/search (empty) ──

    async def test_search_empty_index(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.get("/api/search?q=hello")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 0)

    async def test_search_missing_query(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.get("/api/search")
        self.assertEqual(resp.status, 400)

    async def test_search_invalid_has_tools_returns_400(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.get("/api/search?q=hello&has_tools=maybe")
        self.assertEqual(resp.status, 400)

    async def test_search_invalid_sort_returns_400(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.get("/api/search?q=hello&sort=oldest")
        self.assertEqual(resp.status, 400)

    async def test_search_valid_has_tools_values(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            for value in ("true", "false"):
                with self.subTest(has_tools=value):
                    resp = await self.client.get(f"/api/search?q=hello&has_tools={value}")
                    self.assertEqual(resp.status, 200)
                    body = await resp.json()
                    self.assertIsInstance(body, list)

    async def test_search_valid_sort_values(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            for value in ("relevance", "newest"):
                with self.subTest(sort=value):
                    resp = await self.client.get(f"/api/search?q=hello&sort={value}")
                    self.assertEqual(resp.status, 200)
                    body = await resp.json()
                    self.assertIsInstance(body, list)

    # ── GET /api/search/suggest ──

    async def test_suggest_empty(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.get("/api/search/suggest?q=hel")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIsInstance(body, list)

    async def test_suggest_missing_query(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.get("/api/search/suggest")
        self.assertEqual(resp.status, 400)

    # ── GET /api/search/channels ──

    async def test_channels_empty(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.get("/api/search/channels")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIsInstance(body, list)

    # ── GET /api/search/status ──

    async def test_status(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.get("/api/search/status")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("schema_version", body)
        self.assertIn("indexed_rows", body)
        self.assertIn("db_size_bytes", body)
        self.assertEqual(body["indexed_rows"], 0)
        self.assertEqual(body["schema_version"], "4")

    # ── GET /api/search/context ──

    async def test_context_missing_turn_id(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.get("/api/search/context")
        self.assertEqual(resp.status, 400)

    async def test_context_nonexistent_turn(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.get("/api/search/context?turn_id=nonexistent")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 0)

    # ── Bookmarks CRUD ──

    async def test_bookmark_crud_cycle(self):
        """Create → list → delete bookmark cycle."""
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            # Create bookmark
            resp = await self.client.post(
                "/api/search/bookmarks",
                json={"turn_id": "turn_abc", "label": "Important"},
            )
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body["ok"])

            # List — should have one
            resp = await self.client.get("/api/search/bookmarks")
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertEqual(len(body), 1)
            self.assertEqual(body[0]["turn_id"], "turn_abc")
            self.assertEqual(body[0]["label"], "Important")

            # Delete
            resp = await self.client.delete("/api/search/bookmarks/turn_abc")
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body["ok"])

            # List — should be empty now
            resp = await self.client.get("/api/search/bookmarks")
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertEqual(len(body), 0)

    async def test_set_bookmark_missing_turn_id(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.post(
                "/api/search/bookmarks",
                json={"label": "no turn id"},
            )
        self.assertEqual(resp.status, 400)

    # ── Saved Searches CRUD ──

    async def test_saved_search_crud_cycle(self):
        """Save → list → delete saved search cycle."""
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            # Save a search
            resp = await self.client.post(
                "/api/search/saved",
                json={"name": "Bug reports", "query": "error traceback", "filters": {"channel": "dev"}},
            )
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body["ok"])
            sid = body["id"]
            self.assertIsInstance(sid, int)

            # List — should have one
            resp = await self.client.get("/api/search/saved")
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertEqual(len(body), 1)
            self.assertEqual(body[0]["name"], "Bug reports")
            self.assertEqual(body[0]["query"], "error traceback")

            # Delete
            resp = await self.client.delete(f"/api/search/saved/{sid}")
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body["ok"])

            # List — should be empty
            resp = await self.client.get("/api/search/saved")
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertEqual(len(body), 0)

    async def test_save_search_missing_query(self):
        with patch("thomas.server.routes.search.get_search", return_value=self._search):
            resp = await self.client.post(
                "/api/search/saved",
                json={"name": "No query"},
            )
        self.assertEqual(resp.status, 400)


class TestSearchRoutesRemoteAuth(AioHTTPTestCase):
    """Verify search routes require auth in remote mode."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        super().setUp()

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

    async def test_search_requires_auth(self):
        no_auth = await self.client.get("/api/search?q=test")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/search?q=test",
            headers={"Authorization": "Bearer test-token"},
        )
        # 200 — search works (empty results on empty index)
        self.assertEqual(with_auth.status, 200)

    async def test_status_requires_auth(self):
        no_auth = await self.client.get("/api/search/status")
        self.assertEqual(no_auth.status, 401)

    async def test_bookmarks_requires_auth(self):
        no_auth = await self.client.get("/api/search/bookmarks")
        self.assertEqual(no_auth.status, 401)

    async def test_saved_requires_auth(self):
        no_auth = await self.client.get("/api/search/saved")
        self.assertEqual(no_auth.status, 401)


if __name__ == "__main__":
    unittest.main()
