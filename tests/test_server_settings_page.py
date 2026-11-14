import re
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
        self.assertIn("thomas-eyes-mark", text)
        self.assertIn('data-theme="nebula"', text)
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
        # Two looks only (2026-11-10: "get rid of the theme selector, just make it dark or light"). Dark is stored under the old default's name.
        self.assertIn('<option value="nebula">Dark</option>', text)
        self.assertIn('<option value="light">Light</option>', text)
        for theme in ("dark", "aurora", "sandstone"):
            self.assertNotIn(f'<option value="{theme}">'.format(theme=theme), text)
        self.assertIn("data-thomas-theme-select", text)
        self.assertIn("Isolated Desktop Mode", text)
        self.assertIn("Install Host Service", text)
        self.assertIn("Open Viewer", text)
        self.assertIn('href="/static/settings.style01.css"', text)
        self.assertIn('href="/static/css/workspace_shell.css"', text)
        self.assertIn('href="/static/css/ui_edit_mode.css"', text)
        shared_scripts = (
            "/static/js/workspace_shell.js",
            "/static/js/ui_edit_layout.js",
            "/static/js/ui_edit_mode.js",
        )
        for shared_script in shared_scripts:
            self.assertIn(f'defer src="{shared_script}"', text)
        self.assertLess(text.index(shared_scripts[0]), text.index(shared_scripts[1]))
        self.assertLess(text.index(shared_scripts[1]), text.index(shared_scripts[2]))
        self.assertIn('src="/static/settings.isolated-desktop.js"', text)
        self.assertIn('src="/static/settings.script01.js"', text)
        self.assertLess(text.index("settings.isolated-desktop.js"), text.index("settings.script01.js"))
        self.assertNotIn("unpkg.com", text)
        self.assertIn("Local, deterministic icon fallback", text)
        self.assertIn("Setup unavailable", text)
        self.assertNotIn("Opening Google OAuth consent screen", text)

    async def test_settings_plugins_section_replaces_plugin_management(self):
        resp = await self.client.get("/settings")
        self.assertEqual(resp.status, 200)
        text = await resp.text()

        rail = re.findall(r'data-section="([^"]+)"', text)
        place = rail.index("plugins")
        self.assertEqual((rail[place - 1], rail[place + 1]), ("integrations", "autonomy"))
        self.assertRegex(text, r'id="plugins" class="settings-panel" data-ui-id="settings\.panel\.plugins"')
        self.assertIn("Parts of Thomas you can turn off and on. Thomas keeps running while you do.", text)
        panel = text.split('id="plugins"', 1)[1].split("settings.autonomy-panel.js", 1)[0]
        # Rows come from a fetch: one in the markup would get script01's generic click, which saves nothing.
        self.assertNotIn("toggle-switch", panel)
        self.assertNotIn("Save Changes", panel)
        self.assertNotIn("Reset", panel)
        self.assertIn('<div id="pluginsHost"></div>', panel)
        for gone in ("pluginDirectory", "autoLoadPlugins", "Plugin Management", "settings.advanced.plugins"):
            self.assertNotIn(gone, text)

        self.assertLess(text.index("/static/settings.style01.css"), text.index("/static/css/settings_plugins.css"))
        self.assertLess(text.index("/static/settings.script01.js"), text.index("/static/settings.plugins-panel.js"))
        for asset in ("/static/settings.plugins-panel.js", "/static/css/settings_plugins.css"):
            self.assertEqual((await self.client.get(asset)).status, 200, asset)

    async def test_the_plugins_rail_icon_and_search_lead_to_the_section(self):
        root = Path(__file__).resolve().parents[1]
        web = root / "thomas" / "server" / "web"
        script = (web / "settings.script01.js").read_text(encoding="utf-8")

        self.assertIn(".ph-puzzle-piece::before", (web / "css" / "settings_icons.css").read_text(encoding="utf-8"))
        self.assertIn("'plugin': 'plugins'", script)
        for gone in ("pluginDirectory", "autoLoadPlugins"):
            self.assertNotIn(gone, script)
        self.assertLess(len(script.splitlines()), 800)

    async def test_chat_shell_boots_without_parser_blocking_cdn_assets(self):
        resp = await self.client.get("/")

        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("Thomas Chat", text)

        # Was `assertIn("the chat shell must boot offline", text)` -- a COMMENT
        # marker in chat.html, which was later reworded away. The test went red
        # and stayed red while the behaviour it guards was perfectly fine: the
        # served shell has zero references to any CDN host. Third test found this
        # way, after test_marketplace_uses_native_runtime_shell (red nine days)
        # and test_root_chat_surfaces_gpt56_models_and_distinct_reasoning_efforts.
        # A permanently-red test is how a real regression gets ignored.
        #
        # Pinned to the behaviour instead, and made STRICTER than the three
        # hard-coded hosts it replaces: no parser-blocking asset may come from
        # another origin at all, whichever CDN someone reaches for next.
        external = re.findall(
            r"""<(?:link|script)\b[^>]*?(?:href|src)\s*=\s*["'](https?://[^"']+)""",
            text,
            re.IGNORECASE,
        )
        self.assertEqual(
            external,
            [],
            f"the chat shell must boot offline; these load from another origin: {external}",
        )
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
        layout_css = (root / "thomas" / "server" / "web" / "css" / "layout_styles" / "layout-app-shell.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("main {", settings_css)
        self.assertIn("min-width: 0;\n  min-height: 0;\n  overflow: hidden;", settings_css)
        self.assertIn(".settings-container {", settings_css)
        self.assertIn(".settings-content {", settings_css)
        self.assertIn("overflow-y: auto;", settings_css)
        self.assertIn("@media (max-width: 920px)", settings_css)
        self.assertIn("@media (max-width: 640px)", settings_css)
        self.assertIn("button:focus-visible", settings_css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", settings_css)
        for theme in ("dark", "light", "aurora", "sandstone"):
            self.assertIn(f'html[data-theme="{theme}"]', settings_css)
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
        self.assertIn("const CHAT_THEME_STORAGE_KEY = 'thomas_chat_theme';", script)
        self.assertIn("event.data.type !== 'thomas:theme'", script)
        self.assertEqual(script.count("addEventListener('thomas:themechange'"), 1)
        self.assertLess(
            script.index("document.getElementById('theme')?.addEventListener"),
            script.index("async function saveBreakglassOptIn"),
        )
        self.assertIn("Promise.allSettled([loadSettings(), desktopStatus])", script)
        self.assertIn("if (isMaskedSecret(value)) return;", script)
        self.assertIn("['light', 'sandstone']", script)
        self.assertNotIn("SETTINGS_EXTENSION_SCRIPT", script)
        self.assertIn("/api/onboarding/desktop/status", isolated_desktop_script)
        self.assertIn("/api/onboarding/desktop/install", isolated_desktop_script)
        self.assertIn("/api/onboarding/desktop/trust", isolated_desktop_script)
        self.assertIn("/api/onboarding/desktop/open-viewer", isolated_desktop_script)
        self.assertIn("saveIsolatedDesktopSettings", isolated_desktop_script)
        self.assertIn("installIsolatedDesktopMode", isolated_desktop_script)
        self.assertNotIn("/api/settings", script)

    async def test_settings_ui_editability_contract_protects_sensitive_controls(self):
        root = Path(__file__).resolve().parents[1]
        web = root / "thomas" / "server" / "web"
        html = (web / "settings.html").read_text(encoding="utf-8")
        for panel in ("autonomy", "privacy", "appearance"):
            extracted = (web / f"settings.{panel}-panel.js").read_text(encoding="utf-8")
            markup = extracted.split("`", 1)[1].rsplit("`", 1)[0]
            html = html.replace(f'<script src="/static/settings.{panel}-panel.js"></script>', markup)
        ui_ids = re.findall(r'data-ui-id="([^"]+)"', html)

        self.assertEqual(len(ui_ids), len(set(ui_ids)))
        self.assertRegex(
            html,
            r'data-ui-id="settings\.shell"[^>]*data-ui-policy="root protected"',
        )
        for ui_id in (
            "settings.shell",
            "settings.header",
            "settings.navigation",
            "settings.panel.general",
            "settings.panel.models",
            "settings.panel.advanced",
            "settings.general.agent",
            "settings.appearance.interface",
        ):
            self.assertIn(ui_id, ui_ids)
        for protected_id in (
            "settings.credentials.form",
            "settings.secret.openai",
            "settings.secret.anthropic",
            "settings.secret.google",
            "settings.privacy.security",
            "settings.advanced.maintenance",
            "settings.action.reset-all",
            "settings.action.confirm-destructive",
        ):
            self.assertRegex(
                html,
                rf'data-ui-id="{re.escape(protected_id)}"[^>]*data-ui-policy="protected"',
            )
        self.assertIn('data-ui-constraints="no-move no-edit no-delete no-copy"', html)

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
