"""Opening a second file must not destroy the first file's origin.

Observed in the browser: one conversation, one project, three files -- and three
different ports. Minting for `trey-badlands.html` tore down the origin the
thumbnail of `index.html` was still displaying, so the card that had been
rendering fine collapsed to a broken-document icon. The reverse happened when
the thumbnail refreshed. Nothing was wrong with either page.

A project is ONE app. It gets ONE origin, and files are addressed within it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from thomas.server.routes.deliverable_aiohttp import DeliverablePreviewService


class TestOneOriginPerProject(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "index.html").write_text("<p>shell</p>", encoding="utf-8")
        (self.root / "trey-badlands.html").write_text("<p>game</p>", encoding="utf-8")
        (self.root / "renderer.js").write_text("export const x = 1;", encoding="utf-8")
        self.service = DeliverablePreviewService()
        self.service.configure(main_origin="http://127.0.0.1:8899")
        self.addAsyncCleanup(self.service.stop)
        self.addCleanup(self._tmp.cleanup)

    async def _url(self, tail: str) -> str:
        allowed = {p.name for p in self.root.iterdir() if p.is_file()}
        return await self.service.preview_directory_url(
            subject_id="code:fc_test",
            workspace=self.root,
            tail=tail,
            allowed_files=allowed,
        )

    @staticmethod
    def _port(url: str) -> int:
        return int(urlparse(url).port or 0)

    async def test_two_files_of_one_project_share_an_origin(self) -> None:
        shell = await self._url("index.html")
        game = await self._url("trey-badlands.html")

        self.assertEqual(self._port(shell), self._port(game))

    async def test_reopening_the_first_file_does_not_move_it_again(self) -> None:
        first = await self._url("index.html")
        await self._url("trey-badlands.html")
        again = await self._url("index.html")

        self.assertEqual(self._port(first), self._port(again))

    async def test_the_first_url_still_works_after_the_second_is_minted(self) -> None:
        """The regression was not that the port changed -- it was that the old
        runner was torn down, so a frame already showing that page went blank."""
        shell = await self._url("index.html")
        await self._url("trey-badlands.html")

        self.assertTrue(self.service.is_live_capability(shell.split("/__enter/")[1].split("/")[0]))

    async def test_a_new_file_does_not_move_the_origin(self) -> None:
        """A build that finishes changes the allowlist. Rebuilding the grant for
        that killed the port every frame on screen was loaded from, and Chrome
        painted its network-error page -- which, in a small frame, is a grey box
        with a broken-document icon and no text. It read as a broken game."""
        before = await self._url("index.html")
        (self.root / "level-two.html").write_text("<p>new</p>", encoding="utf-8")
        after = await self._url("index.html")

        self.assertEqual(self._port(before), self._port(after))
        self.assertTrue(self.service.is_live_capability(before.split("/__enter/")[1].split("/")[0]))

    async def test_the_new_file_becomes_servable_without_a_restart(self) -> None:
        """Keeping the origin must not mean keeping a stale allowlist."""
        await self._url("index.html")
        (self.root / "level-two.html").write_text("<p>new</p>", encoding="utf-8")
        url = await self._url("level-two.html")

        self.assertTrue(url.endswith("/level-two.html"))

    async def test_a_different_project_gets_its_own_origin(self) -> None:
        """Isolation is per project, so one generated app can never reach
        another's files through a shared origin."""
        with TemporaryDirectory() as other:
            other_root = Path(other)
            (other_root / "index.html").write_text("<p>other</p>", encoding="utf-8")
            mine = await self._url("index.html")
            theirs = await self.service.preview_directory_url(
                subject_id="code:fc_other",
                workspace=other_root,
                tail="index.html",
                allowed_files={"index.html"},
            )

            self.assertNotEqual(self._port(mine), self._port(theirs))


if __name__ == "__main__":
    unittest.main()
