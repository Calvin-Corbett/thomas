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
        self.assertIn('value="gpt-5.6-sol">GPT-5.6 Sol', text)
        self.assertIn('value="gpt-5.6-terra">GPT-5.6 Terra', text)
        self.assertIn('value="gpt-5.6-luna">GPT-5.6 Luna', text)
        self.assertNotIn("GPT-5.6 Luna (when available)", text)
        self.assertIn('value="gpt-5.5">GPT-5.5', text)
        self.assertIn('value="openai_codex">ChatGPT / Codex (signed in)', text)
        self.assertIn("Isolated Desktop Mode", text)
        self.assertIn("Install Host Service", text)
        self.assertIn("Open Viewer", text)
        self.assertIn('href="/static/settings.style01.css"', text)
        self.assertIn('src="/static/settings.script01.js"', text)
        self.assertNotIn("unpkg.com", text)
        self.assertIn("Local, deterministic icon fallback", text)

    async def test_chat_shell_boots_without_parser_blocking_cdn_assets(self):
        resp = await self.client.get("/")

        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("Thomas Chat", text)
        self.assertIn("the chat shell must boot offline", text)
        self.assertNotIn("fonts.googleapis.com", text)
        self.assertNotIn("fonts.gstatic.com", text)
        self.assertNotIn("unpkg.com", text)

    async def test_favicon_route_is_available_to_ui_and_json_tabs(self):
        resp = await self.client.get("/favicon.ico")

        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "image/svg+xml")
        self.assertIn("<svg", await resp.text())

    async def test_settings_page_scroll_layout_guards_present(self):
        root = Path(__file__).resolve().parents[1]
        settings_css = (root / "thomas" / "server" / "web" / "settings.style01.css").read_text(encoding="utf-8")
        # `part-001a.css` was renamed to `layout-app-shell.css` during the
        # CSS module reorganization. The selectors below moved with it.
        layout_css = (root / "thomas" / "server" / "web" / "css" / "layout_parts" / "layout-app-shell.css").read_text(
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
        # The grouped selector was split into two rules during the layout-shell
        # refactor. Both blocks must still set pointer-events: auto so the
        # settings modal and its children remain interactive while the rest
        # of the page is locked out.
        self.assertIn(".app-layout.settings-active #settingsModal {", layout_css)
        self.assertIn(".app-layout.settings-active #settingsModal * {\n    pointer-events: auto;\n}", layout_css)

    async def test_settings_script_uses_preferences_api_contract(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "thomas" / "server" / "web" / "settings.script01.js").read_text(encoding="utf-8")
        isolated_desktop_script = (root / "thomas" / "server" / "web" / "settings.isolated-desktop.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("const PREFERENCES_API = '/api/preferences';", script)
        self.assertIn("buildPreferencesPatch", script)
        self.assertIn("defaultModel: 'gpt-5.6-sol'", script)
        self.assertIn("defaultProvider: 'openai_codex'", script)
        self.assertIn("raw === 'openai_codex'", script)
        self.assertIn("method: 'PATCH'", script)
        self.assertIn("const SETTINGS_EXTENSION_SCRIPT = '/static/settings.isolated-desktop.js';", script)
        self.assertIn("/api/onboarding/desktop/status", isolated_desktop_script)
        self.assertIn("/api/onboarding/desktop/install", isolated_desktop_script)
        self.assertIn("/api/onboarding/desktop/trust", isolated_desktop_script)
        self.assertIn("/api/onboarding/desktop/open-viewer", isolated_desktop_script)
        self.assertIn("saveIsolatedDesktopSettings", isolated_desktop_script)
        self.assertIn("installIsolatedDesktopMode", isolated_desktop_script)
        self.assertNotIn("/api/settings", script)

    async def test_legacy_settings_expose_breakglass_opt_in_controls(self):
        root = Path(__file__).resolve().parents[1]
        settings_script = (root / "thomas" / "server" / "web" / "settings.script01.js").read_text(encoding="utf-8")
        isolated_desktop_script = (root / "thomas" / "server" / "web" / "settings.isolated-desktop.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("/api/security/breakglass-opt-in", settings_script)
        self.assertIn("protectedOverrideApproval", settings_script)
        self.assertIn("saveBreakglassOptIn", settings_script)
        self.assertIn("Protected Override Approval", isolated_desktop_script)
        self.assertIn('id="protectedOverrideApproval"', isolated_desktop_script)


if __name__ == "__main__":
    unittest.main()
