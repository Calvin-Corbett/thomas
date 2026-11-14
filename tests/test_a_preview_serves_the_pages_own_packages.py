"""A code preview serves the packages the page imports, and still nothing else (2026-09-05).

Calvin's Minecraft game (a Vite project) imports three.js from ``node_modules``.
The preview origin refused that path with a 404 because ``node_modules`` is a
"junk dir" for the artifact listing and the allowlist never named it, so the
page's script never ran and ENTER WORLD could do nothing, while the same
files served plainly play. The smoke check passed because it served the page
another way. Third-party packages a page links are web assets, not secrets;
the boundary on source, credentials and git config beside the page stays.
"""

from __future__ import annotations

import asyncio
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from tempfile import TemporaryDirectory

from thomas.server.routes.deliverable_aiohttp import DeliverablePreviewService


class TestPreviewServesThePagesPackages(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "index.html").write_text('<script type="module" src="./src/main.js"></script>', encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "main.js").write_text(
            "import * as THREE from '../node_modules/three/build/three.module.js';", encoding="utf-8"
        )
        three = self.root / "node_modules" / "three" / "build"
        three.mkdir(parents=True)
        (three / "three.module.js").write_text("export const REVISION = '179';", encoding="utf-8")
        (three / "three.module.js.map").write_text("{}", encoding="utf-8")
        (self.root / "node_modules" / "three" / "package.json").write_text('{"name": "three"}', encoding="utf-8")
        (self.root / "node_modules" / ".package-lock.json").write_text("{}", encoding="utf-8")
        (self.root / "node_modules" / "evil").mkdir()
        (self.root / "node_modules" / "evil" / "setup.py").write_text("PASSWORD = 'x'", encoding="utf-8")
        (self.root / "node_modules" / "evil" / ".npmrc").write_text("//registry/:_authToken=secret", encoding="utf-8")
        (self.root / "secrets.env").write_text("API_KEY=super-secret-value", encoding="utf-8")
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("url = git@example.com:private.git", encoding="utf-8")

        self.service = DeliverablePreviewService()
        self.service.configure(main_origin="http://127.0.0.1:8899")
        self.addAsyncCleanup(self.service.stop)
        self.addCleanup(self._tmp.cleanup)
        # Exactly what the Code route offers: the page and its own web assets, never node_modules.
        url = await self.service.preview_directory_url(
            subject_id="code:test",
            workspace=self.root,
            tail="index.html",
            allowed_files={"index.html", "src/main.js"},
        )
        self.origin = url.rsplit("/__enter/", 1)[0]
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        await self._get(url)

    async def _get(self, target: str) -> int:
        def fetch() -> int:
            try:
                return int(self._opener.open(target, timeout=10).status)
            except urllib.error.HTTPError as exc:
                return int(exc.code)

        return await asyncio.to_thread(fetch)

    async def test_the_module_the_page_imports_is_served(self) -> None:
        self.assertEqual(await self._get(f"{self.origin}/node_modules/three/build/three.module.js"), 200)

    async def test_a_source_map_and_a_package_manifest_are_served(self) -> None:
        self.assertEqual(await self._get(f"{self.origin}/node_modules/three/build/three.module.js.map"), 200)
        self.assertEqual(await self._get(f"{self.origin}/node_modules/three/package.json"), 200)

    async def test_python_and_dotfiles_inside_packages_are_not(self) -> None:
        self.assertEqual(await self._get(f"{self.origin}/node_modules/evil/setup.py"), 404)
        self.assertEqual(await self._get(f"{self.origin}/node_modules/evil/.npmrc"), 404)
        self.assertEqual(await self._get(f"{self.origin}/node_modules/.package-lock.json"), 404)

    async def test_the_boundary_beside_the_page_still_holds(self) -> None:
        self.assertEqual(await self._get(f"{self.origin}/secrets.env"), 404)
        self.assertEqual(await self._get(f"{self.origin}/.git/config"), 404)
