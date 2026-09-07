import re
import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestServerCompanionPage(AioHTTPTestCase):
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

    async def test_companion_page_serves_html(self):
        resp = await self.client.get("/companion")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("Companion Builder", text)
        self.assertIn("Ship", text)
        self.assertIn("/api/companion/v1", text)

    async def test_companion_page_references_and_serves_static_assets(self):
        page_resp = await self.client.get("/companion")
        self.assertEqual(page_resp.status, 200)
        page_text = await page_resp.text()

        css_match = re.search(
            r'href="(?P<url>/static/css/companion\.css(?:\?[^\"]*)?)"',
            page_text,
        )
        js_match = re.search(
            r'src="(?P<url>/static/js/companion\.js(?:\?[^\"]*)?)"',
            page_text,
        )

        self.assertIsNotNone(css_match, "companion.css link missing from /companion")
        self.assertIsNotNone(js_match, "companion.js script missing from /companion")

        css_url = css_match.group("url")
        js_url = js_match.group("url")

        css_resp = await self.client.get(css_url)
        self.assertEqual(css_resp.status, 200, f"expected 200 for {css_url}")

        js_resp = await self.client.get(js_url)
        self.assertEqual(js_resp.status, 200, f"expected 200 for {js_url}")
        js_text = await js_resp.text()
        self.assertIn("setActivePanel", js_text)
        # The rail replaced the mode tabs; these are the destinations it drives.
        self.assertIn("panelHome", js_text)
        self.assertIn("panelChat", js_text)
        self.assertIn("panelApps", js_text)
        self.assertIn("panelAdd", js_text)

    async def test_companion_page_serves_the_shell_stylesheet_and_modules(self):
        page_resp = await self.client.get("/companion")
        page_text = await page_resp.text()

        shell_css = re.search(
            r'href="(?P<url>/static/css/companion_shell\.css(?:\?[^\"]*)?)"', page_text
        )
        self.assertIsNotNone(shell_css, "companion_shell.css link missing from /companion")
        css_resp = await self.client.get(shell_css.group("url"))
        self.assertEqual(css_resp.status, 200)

        # The rail is the shell's only persistent chrome, so it has to be in the
        # served markup rather than built at runtime.
        self.assertIn('id="rail"', page_text)
        self.assertIn('data-rail="home"', page_text)
        self.assertIn('id="railStatus"', page_text)
        self.assertIn('id="homeGrid"', page_text)

        for module in ("companion_home.js", "companion_surface.js"):
            mod_resp = await self.client.get(f"/static/js/{module}")
            self.assertEqual(mod_resp.status, 200, f"expected 200 for {module}")


if __name__ == "__main__":
    unittest.main()
