"""Tests for the Extension Standard: standalone app door + validator."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig
from thomas.server.app_keys import APP_CONFIG
from thomas.server.routes.standalone_app_aiohttp import register_standalone_app_routes

ROOT = Path(__file__).resolve().parent.parent

_INSTALLED_INKWELL = {
    "plugin_id": "inkwell",
    "display_name": "Inkwell",
    "enabled": True,
    "surface": {"entry_html": "web/index.html", "title": "Inkwell"},
}


class TestStandaloneAppRoute(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        app = web.Application()
        app[APP_CONFIG] = AppConfig(memory=MemoryConfig(root="."))
        register_standalone_app_routes(app, require_api_access=lambda request: None)
        return app

    async def test_enabled_plugin_redirects_to_surface(self):
        with patch(
            "thomas.server.routes.standalone_app_aiohttp.get_installed_plugin",
            return_value=dict(_INSTALLED_INKWELL),
        ):
            resp = await self.client.get("/app/inkwell", allow_redirects=False)
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.headers["Location"], "/plugins/inkwell/web/index.html?standalone=1")

    async def test_normalized_record_with_surface_url_redirects(self):
        # get_installed_plugin returns normalized rows: flat surface_url, no nested surface dict.
        plugin = {
            "plugin_id": "inkwell",
            "display_name": "Inkwell",
            "enabled": True,
            "surface_url": "/plugins/inkwell/web/index.html",
        }
        with patch(
            "thomas.server.routes.standalone_app_aiohttp.get_installed_plugin",
            return_value=plugin,
        ):
            resp = await self.client.get("/app/inkwell", allow_redirects=False)
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.headers["Location"], "/plugins/inkwell/web/index.html?standalone=1")

    async def test_not_installed_shows_friendly_page(self):
        with patch(
            "thomas.server.routes.standalone_app_aiohttp.get_installed_plugin",
            return_value=None,
        ):
            resp = await self.client.get("/app/inkwell")
        self.assertEqual(resp.status, 404)
        body = await resp.text()
        self.assertIn("installed yet", body)  # html.escape entity-encodes the apostrophe
        self.assertIn("text/html", resp.headers["Content-Type"])

    async def test_disabled_plugin_shows_friendly_page(self):
        plugin = dict(_INSTALLED_INKWELL, enabled=False)
        with patch(
            "thomas.server.routes.standalone_app_aiohttp.get_installed_plugin",
            return_value=plugin,
        ):
            resp = await self.client.get("/app/inkwell")
        self.assertEqual(resp.status, 403)
        self.assertIn("currently disabled", await resp.text())

    async def test_no_surface_shows_friendly_page(self):
        plugin = dict(_INSTALLED_INKWELL, surface={})
        with patch(
            "thomas.server.routes.standalone_app_aiohttp.get_installed_plugin",
            return_value=plugin,
        ):
            resp = await self.client.get("/app/inkwell")
        self.assertEqual(resp.status, 404)
        self.assertIn("no standalone screen", await resp.text())


class TestExtensionValidator(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_extension.py"), *args],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )

    def test_inkwell_passes_strict(self):
        result = self._run("inkwell", "--strict")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_life_manager_passes_default(self):
        result = self._run("life-manager")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unknown_pack_fails(self):
        result = self._run("does-not-exist")
        self.assertEqual(result.returncode, 2)

    def test_full_catalog_passes_default_mode(self):
        result = self._run("--all")
        self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-500:])


class TestStandardDocs(unittest.TestCase):
    def test_standard_doc_covers_all_types(self):
        text = (ROOT / "docs" / "EXTENSION_STANDARD.md").read_text(encoding="utf-8")
        for marketplace_type in ("app", "plugin", "dependency", "integration"):
            self.assertIn(marketplace_type, text)
        self.assertIn("standalone", text.lower())
        self.assertIn("/app/", text)

    def test_extensions_readme_points_to_standard(self):
        text = (ROOT / "extensions" / "README.md").read_text(encoding="utf-8")
        self.assertIn("EXTENSION_STANDARD.md", text)

    def test_legacy_command_center_normalizes_to_app(self):
        from thomas.server.desktop_plugins_manifest import load_desktop_plugin_manifest_from_data

        manifest = load_desktop_plugin_manifest_from_data(
            {
                "id": "legacy-pack",
                "name": "Legacy Pack",
                "version": "1.0.0",
                "kind": "desktop_plugin",
                "marketplace_type": "command_center",
                "default_nav_section": "command_centers",
                "capabilities": ["legacy_pack.demo"],
                "mode_id": "legacy_pack",
                "entrypoint": "hooks.py",
                "description": "old-style manifest",
                "surface": {"entry_html": "web/index.html", "title": "Legacy"},
            }
        )
        self.assertEqual(manifest.marketplace_type, "app")
        self.assertEqual(manifest.default_nav_section, "apps")

    def test_inkwell_declares_standalone(self):
        import json

        manifest = json.loads((ROOT / "extensions" / "inkwell" / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["standalone"]["enabled"])


if __name__ == "__main__":
    unittest.main()
