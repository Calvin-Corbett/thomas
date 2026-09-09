"""Tests for the Inkwell smart-notepad plugin (routes, smart parsing, manifest)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig
from thomas.server.app_keys import APP_CONFIG
from thomas.server.routes import inkwell_smart
from thomas.server.routes.inkwell_aiohttp import register_inkwell_routes

ROOT = Path(__file__).resolve().parent.parent


class TestInkwellManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "extensions" / "inkwell" / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_core_fields(self):
        self.assertEqual(self.manifest["id"], "inkwell")
        self.assertEqual(self.manifest["kind"], "desktop_plugin")
        self.assertEqual(self.manifest["marketplace_type"], "app")
        self.assertEqual(self.manifest["left_nav_behavior"], "workspace")
        self.assertEqual(self.manifest["surface"]["entry_html"], "web/index.html")

    def test_manifest_files_exist(self):
        plugin_root = ROOT / "extensions" / "inkwell"
        self.assertTrue((plugin_root / self.manifest["entrypoint"]).exists())
        self.assertTrue((plugin_root / self.manifest["surface"]["entry_html"]).exists())
        for name in ("core.js", "sketch.js", "board.js", "speech.js", "alarms.js", "smart.js", "app.js", "style.css"):
            self.assertTrue((plugin_root / "web" / name).exists(), f"missing web/{name}")

    def test_catalog_contains_inkwell(self):
        catalog = json.loads((ROOT / "extensions" / "catalog.json").read_text(encoding="utf-8"))
        entries = [p for p in catalog["packs"] if p.get("id") == "inkwell"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["version"], self.manifest["version"])
        self.assertEqual(entry["mode"], self.manifest["mode"])
        self.assertEqual(entry["marketplace_type"], "app")

    def test_index_html_references_all_scripts(self):
        html = (ROOT / "extensions" / "inkwell" / "web" / "index.html").read_text(encoding="utf-8")
        for name in ("core.js", "sketch.js", "board.js", "speech.js", "alarms.js", "smart.js", "app.js"):
            self.assertIn(name, html)


class TestInkwellSmartParsing(unittest.TestCase):
    def test_extract_plain_json(self):
        payload = inkwell_smart._extract_json_object('{"summary": "hi", "reminders": []}')
        self.assertEqual(payload["summary"], "hi")

    def test_extract_fenced_json_with_prose(self):
        raw = 'Sure! Here you go:\n```json\n{"summary": "ok", "reminders": [], "suggestions": ["a"]}\n```'
        payload = inkwell_smart._extract_json_object(raw)
        self.assertEqual(payload["suggestions"], ["a"])

    def test_extract_garbage_returns_empty(self):
        self.assertEqual(inkwell_smart._extract_json_object("no json here"), {})
        self.assertEqual(inkwell_smart._extract_json_object('{"broken": '), {})

    def test_normalize_filters_bad_reminders(self):
        analysis = inkwell_smart.normalize_analysis(
            {
                "summary": "s",
                "reminders": [
                    {"title": "Call mom", "when": "2026-06-12T15:00", "sound": "bell", "repeat": "none"},
                    {"title": "", "when": "2026-06-12T15:00"},  # no title -> dropped
                    {"title": "No time"},  # no when -> dropped
                    {"title": "Weird", "when": "2026-06-13T09:00", "sound": "kazoo", "repeat": "hourly"},
                ],
                "suggestions": ["do a thing", "", 42],
            }
        )
        self.assertEqual(len(analysis["reminders"]), 2)
        self.assertEqual(analysis["reminders"][0]["sound"], "bell")
        self.assertEqual(analysis["reminders"][1]["sound"], "chime")  # kazoo coerced
        self.assertEqual(analysis["reminders"][1]["repeat"], "none")  # hourly coerced
        self.assertEqual(analysis["suggestions"], ["do a thing", "42"])

    def test_normalize_empty_payload(self):
        analysis = inkwell_smart.normalize_analysis({})
        self.assertEqual(
            analysis,
            {"summary": "", "category": "other", "purpose": "", "reminders": [], "observations": [], "suggestions": []},
        )

    def test_normalize_observations_and_category(self):
        analysis = inkwell_smart.normalize_analysis(
            {
                "category": "TASK",
                "purpose": "p",
                "observations": [{"text": "tracks gardening", "why": "tomatoes"}, {"text": ""}, "junk"],
            }
        )
        self.assertEqual(analysis["category"], "task")
        self.assertEqual(analysis["observations"], [{"text": "tracks gardening", "why": "tomatoes"}])


class TestInkwellRoutes(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self._tmp = tempfile.mkdtemp(prefix="inkwell-test-")
        self._enabled_patch = patch("thomas.server.routes.inkwell_aiohttp.is_plugin_enabled", return_value=True)
        self._enabled_patch.start()
        self.addCleanup(self._enabled_patch.stop)
        app = web.Application()
        app[APP_CONFIG] = AppConfig(memory=MemoryConfig(root=self._tmp))
        register_inkwell_routes(app, require_api_access=lambda request: None)
        return app

    async def test_bootstrap_empty_state(self):
        resp = await self.client.get("/api/plugins/inkwell/bootstrap")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["state"]["notes"], [])
        self.assertEqual(payload["state"]["reminders"], [])

    async def test_note_crud_roundtrip(self):
        create = await self.client.post(
            "/api/plugins/inkwell/notes",
            json={
                "title": "Groceries",
                "blocks": [{"x": 10, "y": 20, "w": 200, "text": "milk, eggs"}],
                "strokes": [{"tool": "pen", "color": "#111", "size": 3, "points": [[1, 2], [3, 4]]}],
            },
        )
        self.assertEqual(create.status, 201)
        note = (await create.json())["item"]
        self.assertEqual(note["title"], "Groceries")
        self.assertEqual(len(note["blocks"]), 1)
        self.assertEqual(note["strokes"][0]["points"], [[1.0, 2.0], [3.0, 4.0]])

        patch_resp = await self.client.patch(
            f"/api/plugins/inkwell/notes/{note['id']}",
            json={"title": "Groceries v2", "strokes": []},
        )
        self.assertEqual(patch_resp.status, 200)
        updated = (await patch_resp.json())["item"]
        self.assertEqual(updated["title"], "Groceries v2")
        self.assertEqual(updated["strokes"], [])
        self.assertEqual(len(updated["blocks"]), 1)  # untouched by partial patch

        delete = await self.client.delete(f"/api/plugins/inkwell/notes/{note['id']}")
        self.assertEqual(delete.status, 200)
        listing = await (await self.client.get("/api/plugins/inkwell/notes")).json()
        self.assertEqual(listing["items"], [])

    async def test_reminder_validation(self):
        bad = await self.client.post("/api/plugins/inkwell/reminders", json={"when": "2026-06-12T08:00"})
        self.assertEqual(bad.status, 400)
        good = await self.client.post(
            "/api/plugins/inkwell/reminders",
            json={"title": "Stand-up", "when": "2026-06-12T08:00", "sound": "kazoo", "repeat": "sometimes"},
        )
        self.assertEqual(good.status, 201)
        reminder = (await good.json())["item"]
        self.assertEqual(reminder["sound"], "chime")
        self.assertEqual(reminder["repeat"], "none")
        self.assertEqual(reminder["fired_at"], "")

    async def test_unknown_collection_rejected(self):
        resp = await self.client.get("/api/plugins/inkwell/passwords")
        self.assertEqual(resp.status, 400)

    async def test_analyze_returns_normalized_analysis(self):
        async def fake_analyze(config, text, *, local_now=""):
            self.assertIn("dentist", text)
            return {"summary": "dentist note", "reminders": [], "suggestions": ["book it"]}

        with patch.object(inkwell_smart, "analyze_text", side_effect=fake_analyze):
            resp = await self.client.post(
                "/api/plugins/inkwell/analyze",
                json={"text": "dentist tomorrow 3pm", "local_now": "2026-06-11T10:00"},
            )
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertEqual(payload["analysis"]["suggestions"], ["book it"])

    async def test_analyze_unavailable_is_503(self):
        async def no_model(config, text, *, local_now=""):
            raise inkwell_smart.SmartAnalysisUnavailable("no model configured")

        with patch.object(inkwell_smart, "analyze_text", side_effect=no_model):
            resp = await self.client.post("/api/plugins/inkwell/analyze", json={"text": "hello"})
        self.assertEqual(resp.status, 503)
        payload = await resp.json()
        self.assertFalse(payload["ok"])

    async def test_analyze_requires_text(self):
        resp = await self.client.post("/api/plugins/inkwell/analyze", json={})
        self.assertEqual(resp.status, 400)

    async def test_disabled_plugin_returns_404(self):
        with patch("thomas.server.routes.inkwell_aiohttp.is_plugin_enabled", return_value=False):
            resp = await self.client.get("/api/plugins/inkwell/bootstrap")
        self.assertEqual(resp.status, 404)


if __name__ == "__main__":
    unittest.main()
