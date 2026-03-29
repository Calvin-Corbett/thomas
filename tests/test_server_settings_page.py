import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

import thomas.core.rules_of_road as rules_of_road
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig

if not hasattr(rules_of_road, "build_remediation_prompt"):
    rules_of_road.build_remediation_prompt = lambda *args, **kwargs: ""
if not hasattr(rules_of_road, "evaluate_rules"):
    rules_of_road.evaluate_rules = lambda *args, **kwargs: {}

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
        self.assertIn("Workflow Mode", text)
        self.assertIn("Isolated Desktop Mode", text)
        self.assertIn("Install Host Service", text)
        self.assertIn("Open Viewer", text)

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
        self.assertIn(
            ".app-layout.settings-active .main-content > :not(#settingsModal) {\n    pointer-events: none !important;\n}",
            layout_css,
        )
        self.assertIn(
            ".app-layout.settings-active #settingsModal,\n.app-layout.settings-active #settingsModal * {\n    pointer-events: auto;\n}",
            layout_css,
        )

    async def test_settings_script_uses_preferences_api_contract(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "thomas" / "server" / "web" / "settings.script01.js").read_text(encoding="utf-8")

        self.assertIn("const PREFERENCES_API = '/api/preferences';", script)
        self.assertIn("buildPreferencesPatch", script)
        self.assertIn("method: 'PATCH'", script)
        self.assertIn("/api/onboarding/desktop/status", script)
        self.assertIn("/api/onboarding/desktop/install", script)
        self.assertIn("/api/onboarding/desktop/trust", script)
        self.assertIn("/api/onboarding/desktop/open-viewer", script)
        self.assertIn("saveIsolatedDesktopSettings", script)
        self.assertIn("installIsolatedDesktopMode", script)
        self.assertNotIn("/api/settings", script)


if __name__ == "__main__":
    unittest.main()
