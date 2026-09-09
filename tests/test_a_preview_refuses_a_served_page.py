"""A directory preview refuses a page that only a server can render (2026-09-07).

The self-edit demo offered Thomas's own ``chat.html`` from a candidate copy
through the static directory preview. The browser console showed what that
page is without its server: eleven ``404`` loads for ``/static/js/...`` and
``Uncaught TypeError: Cannot destructure property 'THEMES' of
'window.ThomasChatThemes' as it is undefined``. "Demo ready" would have put a
blank shell with a script error in front of the user and called it the change.

The rule is the one build_verify's smoke and web.playtest already follow
(``thomas/tools/web_preflight.is_served_page``): a page whose root-absolute
links resolve nowhere under the tree is an application shell, not a standalone
artifact, and is never served from disk. The preview service now refuses such
a tail with the unresolved link in its reason, before any origin is started;
a page whose root-absolute links do resolve is still previewed.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from thomas.server.routes.deliverable_aiohttp import DeliverablePreviewService


class TestPreviewRefusesAServedPage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Thomas's shell, as the candidate copy holds it: the script it links
        # exists only once the aiohttp app mounts /static.
        (self.root / "chat.html").write_text(
            '<!doctype html><script src="/static/js/chat_themes.js"></script><div id="tc-shell"></div>',
            encoding="utf-8",
        )
        (self.root / "js").mkdir()
        (self.root / "js" / "chat_themes.js").write_text("window.ThomasChatThemes = {THEMES: []};", encoding="utf-8")
        # A standalone page beside it whose root-absolute link resolves in the tree.
        (self.root / "index.html").write_text('<script src="/js/chat_themes.js"></script>', encoding="utf-8")
        self.service = DeliverablePreviewService()
        self.service.configure(main_origin="http://127.0.0.1:8899")
        self.addAsyncCleanup(self.service.stop)
        self.addCleanup(self._tmp.cleanup)

    async def test_the_shell_is_refused_with_the_link_that_cannot_resolve(self) -> None:
        with self.assertRaises(ValueError) as caught:
            await self.service.preview_directory_url(
                subject_id="self-edit:test", workspace=self.root, tail="chat.html", allowed_files={"chat.html"}
            )
        self.assertIn("/static/js/chat_themes.js", str(caught.exception))
        self.assertIn("server", str(caught.exception).lower())
        self.assertEqual(self.service.active_grants(), 0)

    async def test_a_page_whose_root_links_resolve_is_still_previewed(self) -> None:
        url = await self.service.preview_directory_url(
            subject_id="code:test",
            workspace=self.root,
            tail="index.html",
            allowed_files={"index.html", "js/chat_themes.js"},
        )
        self.assertIn("/__enter/", url)
        self.assertTrue(url.endswith("/index.html"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
