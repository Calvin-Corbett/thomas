"""A canvas element is not a drawing.

The smoke check accepted `bool(receipt["canvas"])` as proof that a page had
rendered. A game that draws nothing has exactly the same DOM as a game that
draws perfectly -- one `<canvas>` tag either way -- so the check passed the
builds it exists to catch. These tests run a real headless browser against
pages that differ only in whether anything reaches the canvas.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from thomas.forge.anvil.web_artifact_smoke import _browser_executable, smoke_html_artifacts

_PAGE = """<!doctype html>
<html><head><title>t</title></head><body style="margin:0">
<canvas id="c" width="240" height="160"></canvas>
<script>
  const ctx = document.getElementById('c').getContext('2d');
  __DRAW__
</script>
</body></html>
"""

_DRAWS = "ctx.fillStyle = '#c0562b'; ctx.fillRect(20, 20, 120, 80);"
_DRAWS_NOTHING = "void ctx;"


@unittest.skipIf(_browser_executable() is None, "no Chrome or Edge available for a real smoke run")
class TestCanvasPaintIsProved(unittest.TestCase):
    def _smoke(self, draw: str):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "game.html").write_text(_PAGE.replace("__DRAW__", draw), encoding="utf-8")
            return smoke_html_artifacts(root, ["game.html"], timeout=30)

    def test_a_game_that_draws_passes(self) -> None:
        result = self._smoke(_DRAWS)

        self.assertTrue(result.attempted)
        self.assertTrue(result.ok, result.summary)
        self.assertEqual(result.receipts[0]["canvas"]["paint"], "painted")

    def test_a_game_that_draws_nothing_fails(self) -> None:
        """This is the case that used to pass. It is the whole point."""
        result = self._smoke(_DRAWS_NOTHING)

        self.assertTrue(result.attempted)
        self.assertFalse(result.ok, "an untouched canvas must not be called rendered")
        # Plain language first: the owner reads these lines, and "the canvas was
        # never drawn to" means nothing to someone who does not write web code.
        self.assertIn("blank picture area", result.summary)
        self.assertIn("nothing was ever drawn to the canvas", result.summary)

    def test_a_canvas_nobody_ever_drew_through_is_not_a_failure(self) -> None:
        """Thomas's own shell page carries a leftover canvas at the default
        300x150 and works perfectly by framing the game in an iframe. A canvas
        that was never asked for a drawing context is dead markup, not a failed
        render, and rejecting it would block a good delivery -- the same mistake
        as passing a bad one, pointed the other way."""
        page = """<!doctype html>
<html><head><title>t</title></head><body>
<canvas id="leftover"></canvas>
<p>The real content lives here.</p>
</body></html>
"""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shell.html").write_text(page, encoding="utf-8")
            result = smoke_html_artifacts(root, ["shell.html"], timeout=30)

        self.assertTrue(result.ok, result.summary)
        self.assertEqual(result.receipts[0]["canvas"]["context"], "")
        self.assertEqual(result.receipts[0]["canvas"]["paint"], "unverifiable")

    def test_the_failure_names_the_file_and_the_reason(self) -> None:
        """A build that fails must say what to go fix."""
        result = self._smoke(_DRAWS_NOTHING)

        self.assertIn("game.html", result.summary)

    def test_webgl_is_not_called_blank(self) -> None:
        """A WebGL canvas without preserveDrawingBuffer reads back empty even
        while it is drawing every frame. Failing that would reject working work,
        so it is reported as unverifiable and allowed through."""
        page = """<!doctype html>
<html><head><title>t</title></head><body style="margin:0">
<canvas id="c" width="240" height="160"></canvas>
<script>
  const gl = document.getElementById('c').getContext('webgl');
  if (gl) { gl.clearColor(0.1, 0.2, 0.3, 1); gl.clear(gl.COLOR_BUFFER_BIT); }
</script>
</body></html>
"""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gl.html").write_text(page, encoding="utf-8")
            result = smoke_html_artifacts(root, ["gl.html"], timeout=30)

        self.assertTrue(result.attempted)
        self.assertEqual(result.receipts[0]["canvas"]["context"], "webgl")
        self.assertEqual(result.receipts[0]["canvas"]["paint"], "unverifiable")
        self.assertTrue(result.ok, result.summary)


if __name__ == "__main__":
    unittest.main()
