"""Tests for thomas.server.routes.goals (task kanban CRUD + stats)."""

import tempfile
import types
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class FakePE:
    """Lightweight stand-in for PersistenceEngine with goal CRUD."""

    def __init__(self):
        self.goals = []
        self._next_id = 1

    def add_goal(self, text, priority="medium"):
        gid = str(self._next_id)
        self._next_id += 1
        goal = {
            "id": gid,
            "text": text,
            "priority": priority,
            "status": "open",
            "created": "2026-01-15T12:00:00+00:00",
        }
        self.goals.append(goal)
        return goal

    def close_goal(self, gid):
        for g in self.goals:
            if str(g.get("id")) == str(gid):
                g["status"] = "done"

    def delete_goal(self, gid):
        self.goals = [g for g in self.goals if str(g.get("id")) != str(gid)]

    def save(self):
        pass


class TestGoalsRoutesLocal(AioHTTPTestCase):
    """Test goals CRUD routes under local access mode."""

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._fake_pe = FakePE()

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

    # ── GET /api/goals (empty) ──

    async def test_goals_list_empty(self):
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.get("/api/goals")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("open", body)
        self.assertIn("in_progress", body)
        self.assertIn("done", body)
        self.assertEqual(len(body["open"]), 0)

    # ── POST /api/goals (create) ──

    async def test_create_goal(self):
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.post(
                "/api/goals",
                json={"text": "Ship v1.0", "priority": "high"},
            )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["goal"]["text"], "Ship v1.0")
        self.assertEqual(body["goal"]["priority"], "high")
        self.assertEqual(body["goal"]["status"], "open")

    async def test_create_goal_missing_text(self):
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.post("/api/goals", json={"priority": "low"})
        self.assertEqual(resp.status, 400)

    async def test_create_goal_with_tags_and_notes(self):
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.post(
                "/api/goals",
                json={
                    "text": "Research options",
                    "priority": "medium",
                    "tags": ["research", "urgent"],
                    "notes": "Check three vendors",
                },
            )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])

    # ── GET /api/goals (with data) ──

    async def test_goals_list_with_data(self):
        self._fake_pe.add_goal("Task A", priority="high")
        self._fake_pe.add_goal("Task B", priority="low")
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.get("/api/goals")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(len(body["open"]), 2)

    # ── PATCH /api/goals/{goal_id} ──

    async def test_update_goal_status(self):
        self._fake_pe.add_goal("Do something", priority="medium")
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.patch(
                "/api/goals/1",
                json={"status": "in_progress"},
            )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["goal"]["status"], "in_progress")

    async def test_update_goal_to_done(self):
        self._fake_pe.add_goal("Finish it", priority="medium")
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.patch(
                "/api/goals/1",
                json={"status": "done"},
            )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["goal"]["status"], "done")
        self.assertIn("done_at", body["goal"])

    async def test_update_nonexistent_goal(self):
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.patch(
                "/api/goals/999",
                json={"status": "done"},
            )
        self.assertEqual(resp.status, 404)

    # ── DELETE /api/goals/{goal_id} ──

    async def test_delete_goal(self):
        self._fake_pe.add_goal("Remove me", priority="low")
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.delete("/api/goals/1")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(self._fake_pe.goals), 0)

    async def test_delete_nonexistent_goal_with_delete_fn(self):
        """When PE has delete_goal(), handler trusts it and returns ok."""
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.delete("/api/goals/999")
        self.assertEqual(resp.status, 200)  # PE.delete_goal trusted

    async def test_delete_nonexistent_goal_fallback_404(self):
        """When PE lacks delete_goal(), handler checks list length and returns 404."""
        class MinimalPE:
            def __init__(self):
                self.goals = []
            def save(self):
                pass
        minimal_pe = MinimalPE()
        with patch("thomas.server.routes.goals.get_persistence", return_value=minimal_pe):
            resp = await self.client.delete("/api/goals/999")
        self.assertEqual(resp.status, 404)

    # ── GET /api/goals/stats ──

    async def test_stats_empty(self):
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.get("/api/goals/stats")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["open_n"], 0)
        self.assertEqual(body["ip_n"], 0)
        self.assertEqual(body["done_n"], 0)
        self.assertIn("generated_at", body)

    async def test_stats_with_goals(self):
        self._fake_pe.add_goal("Open task", priority="high")
        g2 = self._fake_pe.add_goal("Done task", priority="low")
        # mark g2 as done
        for g in self._fake_pe.goals:
            if g["id"] == g2["id"]:
                g["status"] = "done"
                g["done_at"] = "2026-01-15T13:00:00+00:00"
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.get("/api/goals/stats")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["open_n"], 1)
        self.assertEqual(body["done_n"], 1)

    # ── ETag 304 ──

    async def test_etag_304(self):
        self._fake_pe.add_goal("ETag test", priority="medium")
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            r1 = await self.client.get("/api/goals")
            self.assertEqual(r1.status, 200)
            etag = r1.headers.get("ETag")
            self.assertTrue(etag)

            r2 = await self.client.get(
                "/api/goals",
                headers={"If-None-Match": etag},
            )
            self.assertEqual(r2.status, 304)

    # ── Rank sorting ──

    async def test_rank_sorting(self):
        self._fake_pe.add_goal("First", priority="medium")
        self._fake_pe.add_goal("Second", priority="medium")
        # Give goal 2 a lower rank (sorts first)
        self._fake_pe.goals[0]["rank"] = 10.0
        self._fake_pe.goals[1]["rank"] = 0.0
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.get("/api/goals")
        body = await resp.json()
        self.assertEqual(body["open"][0]["id"], "2")  # lower rank sorts first

    # ── Status aliases ──

    async def test_status_alias_doing(self):
        self._fake_pe.add_goal("Alias test", priority="medium")
        with patch("thomas.server.routes.goals.get_persistence", return_value=self._fake_pe):
            resp = await self.client.patch(
                "/api/goals/1",
                json={"status": "doing"},
            )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["goal"]["status"], "in_progress")


class TestGoalsRoutesRemoteAuth(AioHTTPTestCase):
    """Verify goals routes require auth in remote mode."""

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

    async def test_goals_list_requires_auth(self):
        no_auth = await self.client.get("/api/goals")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/goals",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)

    async def test_goals_create_requires_auth(self):
        no_auth = await self.client.post(
            "/api/goals",
            json={"text": "test", "priority": "medium"},
        )
        self.assertEqual(no_auth.status, 401)

    async def test_goals_stats_requires_auth(self):
        no_auth = await self.client.get("/api/goals/stats")
        self.assertEqual(no_auth.status, 401)


if __name__ == "__main__":
    unittest.main()
