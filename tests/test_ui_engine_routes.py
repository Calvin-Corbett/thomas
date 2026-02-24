from __future__ import annotations

import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.server.routes.ui_engine_aiohttp import register_ui_engine_routes


class _StubUIEngine:
    def __init__(self) -> None:
        self.audit_calls: list[dict[str, object]] = []
        self.asset_calls: list[dict[str, object]] = []

    def status_snapshot(self) -> dict:
        return {
            "running": True,
            "enabled": True,
            "cycles_completed": 3,
            "active_cycle": False,
            "last_cycle_at": "2026-02-23T00:00:00+00:00",
            "last_score": 88,
            "last_warning_count": 2,
        }

    def last_report(self) -> dict:
        return {"score": 88, "warning_count": 2}

    def list_effects(self, *, category: str = "") -> list[dict]:
        rows = [
            {"id": "e1", "category": "motion", "name": "Motion Effect"},
            {"id": "e2", "category": "quality", "name": "Quality Effect"},
        ]
        if not category:
            return rows
        return [row for row in rows if row["category"] == category]

    def run_cycle_once(self, *, reason: str = "manual", force: bool = False) -> dict:
        self.audit_calls.append({"reason": reason, "force": force})
        return {"ok": True, "reason": reason, "force": force, "score": 90, "warning_count": 1}

    def search_assets(self, query: str, *, limit: int = 12, providers=None) -> dict:  # type: ignore[no-untyped-def]
        self.asset_calls.append({"query": query, "limit": limit, "providers": providers})
        return {
            "ok": True,
            "query": query,
            "count": 1,
            "assets": [
                {
                    "provider": "openverse",
                    "id": "ov-123",
                    "title": "Hero image",
                    "asset_url": "https://example.test/hero.jpg",
                }
            ],
            "providers": [{"provider": "openverse", "ok": True, "count": 1}],
        }

    def review_ui_edits(self, *, intent: str = "", changed_paths=None, strict: bool = True) -> dict:  # type: ignore[no-untyped-def]
        if strict and "mismatch" in intent.lower():
            return {
                "ok": True,
                "verdict": "fail",
                "score": 41,
                "issues": [{"id": "review.intent_alignment_low"}],
                "intent": {"text": intent, "alignment_score": 0.1},
            }
        return {
            "ok": True,
            "verdict": "pass",
            "score": 96,
            "issues": [],
            "intent": {"text": intent, "alignment_score": 0.9},
            "paths": list(changed_paths or []),
        }


class TestUIEngineRoutes(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.stub = _StubUIEngine()
        self.patcher = patch(
            "thomas.server.routes.ui_engine_aiohttp.get_ui_workflow_engine",
            return_value=self.stub,
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        super().tearDown()

    async def get_application(self):
        app = web.Application()

        async def _read_json(request: web.Request):  # type: ignore[no-untyped-def]
            try:
                return await request.json()
            except Exception:
                raise web.HTTPBadRequest(text="invalid json")

        register_ui_engine_routes(
            app,
            require_api_access=lambda request: None,
            read_json=_read_json,
        )
        return app

    async def test_status_endpoint_returns_snapshot(self):
        resp = await self.client.get("/api/ui-engine/status")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        status = body.get("status") or {}
        self.assertEqual(int(status.get("cycles_completed") or 0), 3)

    async def test_effects_endpoint_filters_by_category(self):
        resp = await self.client.get("/api/ui-engine/effects?category=motion")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        effects = body.get("effects") or []
        self.assertEqual(len(effects), 1)
        self.assertEqual(str(effects[0].get("category") or ""), "motion")

    async def test_audit_endpoint_runs_cycle(self):
        resp = await self.client.post("/api/ui-engine/audit", json={"reason": "manual-check", "force": True})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(str(body.get("reason") or ""), "manual-check")
        self.assertEqual(len(self.stub.audit_calls), 1)
        self.assertEqual(self.stub.audit_calls[0]["force"], True)

    async def test_assets_search_requires_query(self):
        resp = await self.client.post("/api/ui-engine/assets/search", json={"query": "x"})
        self.assertEqual(resp.status, 400)

    async def test_assets_search_returns_results(self):
        resp = await self.client.post(
            "/api/ui-engine/assets/search",
            json={"query": "hero gradient", "limit": 5, "providers": ["openverse"]},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(int(body.get("count") or 0), 1)
        self.assertEqual(len(self.stub.asset_calls), 1)
        self.assertEqual(str(self.stub.asset_calls[0]["query"] or ""), "hero gradient")

    async def test_review_endpoint_returns_200_for_pass(self):
        resp = await self.client.post(
            "/api/ui-engine/review",
            json={
                "intent": "Improve button contrast and hover states",
                "changed_paths": ["thomas/server/web/css/components.css"],
                "strict": True,
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(str(body.get("verdict") or ""), "pass")

    async def test_review_endpoint_returns_409_for_fail(self):
        resp = await self.client.post(
            "/api/ui-engine/review",
            json={
                "intent": "Intent mismatch case",
                "changed_paths": ["thomas/server/web/css/components.css"],
                "strict": True,
            },
        )
        self.assertEqual(resp.status, 409)
        body = await resp.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(str(body.get("verdict") or ""), "fail")


if __name__ == "__main__":
    unittest.main()
