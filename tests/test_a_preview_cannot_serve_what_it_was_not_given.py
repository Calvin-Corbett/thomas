"""A code preview serves the page's web assets and nothing else.

Code results are served from a real isolated loopback origin so that relative
paths, dynamic imports and fetches behave as they will for the owner. That
origin sits on a directory of the owner's own project, which may hold source,
credentials and a git config beside the page.

The changelog claims previewing a page "cannot hand out source or secrets
sitting next to it". That claim was true when written and had no test behind it,
which is the state in which a security property quietly stops being true.
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


class TestPreviewServesOnlyTheAllowlist(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "index.html").write_text("<p>the page</p>", encoding="utf-8")
        (self.root / "app.js").write_text("const value = 1;", encoding="utf-8")
        (self.root / "secrets.env").write_text("API_KEY=super-secret-value", encoding="utf-8")
        (self.root / "server.py").write_text("PASSWORD = 'hunter2'", encoding="utf-8")
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("url = git@example.com:private.git", encoding="utf-8")

        self.service = DeliverablePreviewService()
        self.service.configure(main_origin="http://127.0.0.1:8899")
        self.addAsyncCleanup(self.service.stop)
        self.addCleanup(self._tmp.cleanup)

        # Exactly what the Code route passes: web assets only.
        url = await self.service.preview_directory_url(
            subject_id="code:test",
            workspace=self.root,
            tail="index.html",
            allowed_files={"index.html", "app.js"},
        )
        self.origin = url.rsplit("/__enter/", 1)[0]
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        await self._get(url)  # handshake sets the capability cookie

    async def _get(self, target: str) -> int:
        """Fetch off-loop: urllib is synchronous and the preview server runs in
        THIS event loop, so calling it inline deadlocks."""

        def fetch() -> int:
            # HTTPError only. A refusal is the result being measured, but a
            # connection or timeout failure is NOT a refusal -- swallowing it
            # would report 404 for a preview that never answered at all, and
            # this test would pass while proving nothing.
            try:
                return int(self._opener.open(target, timeout=10).status)
            except urllib.error.HTTPError as exc:
                return int(exc.code)

        return await asyncio.to_thread(fetch)

    async def test_the_page_itself_is_served(self) -> None:
        self.assertEqual(await self._get(f"{self.origin}/index.html"), 200)

    async def test_an_allowed_asset_is_served(self) -> None:
        self.assertEqual(await self._get(f"{self.origin}/app.js"), 200)

    async def test_credentials_sitting_beside_the_page_are_not(self) -> None:
        self.assertEqual(await self._get(f"{self.origin}/secrets.env"), 404)

    async def test_source_beside_the_page_is_not(self) -> None:
        self.assertEqual(await self._get(f"{self.origin}/server.py"), 404)

    async def test_the_projects_git_config_is_not(self) -> None:
        self.assertEqual(await self._get(f"{self.origin}/.git/config"), 404)

    async def test_a_file_that_exists_but_was_not_offered_is_refused(self) -> None:
        """The allowlist is the authority, not the file's suffix. A stylesheet
        the caller did not include stays out even though it is a web asset."""
        (self.root / "extra.css").write_text("body { color: red }", encoding="utf-8")

        self.assertEqual(await self._get(f"{self.origin}/extra.css"), 404)


if __name__ == "__main__":
    unittest.main()
