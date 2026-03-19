import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestServerSettingsPage(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_settings_page_serves_html(self):
        resp = await self.client.get("/settings")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("Settings", text)
        self.assertIn("Thomas Agent Settings", text)
        self.assertIn("searchInput", text)
        self.assertIn("settings-sidebar", text)
        self.assertIn("settings-content", text)
        self.assertIn("General Settings", text)
        self.assertIn("Models & Providers", text)

    async def test_settings_page_scroll_layout_guards_present(self):
        root = Path(__file__).resolve().parents[1]
        settings_css = (root / "thomas" / "server" / "web" / "settings.style01.css").read_text(encoding="utf-8")
        layout_css = (root / "thomas" / "server" / "web" / "css" / "layout_parts" / "part-001a.css").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "main {\n      display: flex;\n      flex: 1;\n      min-width: 0;\n      min-height: 0;",
            settings_css,
        )
        self.assertIn(
            ".settings-container {\n      flex: 1;\n      min-width: 0;\n      min-height: 0;",
            settings_css,
        )
        self.assertIn(
            ".settings-content {\n      flex: 1;\n      min-width: 0;\n      min-height: 0;\n      overflow-y: auto;",
            settings_css,
        )
        self.assertIn(
            ".main-content {\n    flex: 1;\n    display: flex;\n    flex-direction: column;\n    position: relative;\n    min-width: 0;\n    min-height: 0;",
            layout_css,
        )
        self.assertIn(
            ".main-content > * {\n    min-width: 0;\n    min-height: 0;\n}",
            layout_css,
        )

    async def test_settings_script_uses_preferences_api_contract(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "thomas" / "server" / "web" / "settings.script01.js").read_text(encoding="utf-8")

        self.assertIn("const PREFERENCES_API = '/api/preferences';", script)
        self.assertIn("buildPreferencesPatch", script)
        self.assertIn("method: 'PATCH'", script)
        self.assertNotIn("/api/settings", script)


if __name__ == "__main__":
    unittest.main()
