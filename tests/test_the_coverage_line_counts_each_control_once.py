"""A control two probes both drove is one control, not two.

``exercised_controls`` was ``pressable.length + (alreadyDriven ? 1 : 0)``. The
smoke's probes overlap: the start probe, the nav probe and the type-then-press
probe all click controls that the press probe then re-selects into
``pressable`` a moment later. So a button both of them drove was counted twice,
while a nav probe that clicked eight controls contributed one.

The double count could exceed the number of controls on the page, and
``web_artifact_smoke.py`` clamps ``total - exercised`` at zero -- so it never
printed a negative. It printed NOTHING, deleting the coverage line on a page
that really did have controls nobody pressed. Coverage silence reads as
coverage.

MEASURED with a matched pair. Two seven-button pages, byte-identical apart from
the FIRST BUTTON'S LABEL, so both take the same press path and both leave
exactly one button ("Golf") untouched::

    first button    interactive  pressed  exercised   coverage line
    "Alpha"              7          6         6       "1 of 7 control(s) not exercised"
    "Start Game"         7          6         7       (none)                   <- before
    "Start Game"         7          6         6       "1 of 7 control(s) not exercised"  <- after

The second run's own receipt contradicted itself: it reported
``pressed_controls: 6`` beside ``exercised_controls: 7``, and its summary listed
the same button twice -- ``clicked:Start Game, pressed:Start Game``.

The same overlap on a Start screen that builds a 20-cell board::

    board created by the Start press   exercised 7 -> 6, "14 of 21" -> "15 of 21"

Six distinct nodes were driven in that run, which is what 6 now says.

Nothing about which controls get pressed changes: ``pressed_controls`` is 6 in
every row above, before and after. Only the count of DISTINCT controls driven,
and therefore the coverage line, is corrected.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from thomas.forge.anvil.web_artifact_smoke import _browser_executable, smoke_html_artifacts

# Seven buttons, none of them destructive- or download-shaped, no text field and
# no nav container -- so the ONLY probes that run are the start probe (when the
# first label invites it) and the press probe, whose slice cap is six.
_PAGE = """<!doctype html><meta charset=utf-8><title>seven</title>
<h1>Seven</h1>
<button class=k>__FIRST__</button>
<button class=k>Bravo</button>
<button class=k>Charlie</button>
<button class=k>Delta</button>
<button class=k>Echo</button>
<button class=k>Foxtrot</button>
<button class=k>Golf</button>
<p id=out>idle</p>
<script>
let n = 0;
document.querySelectorAll('.k').forEach((b) => {
  b.onclick = () => { n += 1; document.getElementById('out').textContent = b.textContent + ' ' + n; };
});
</script>
"""


@unittest.skipIf(_browser_executable() is None, "no Chrome or Edge available for a real smoke run")
class TestTheCoverageLineCountsEachControlOnce(unittest.TestCase):
    def _run(self, first_label: str) -> tuple[str, dict]:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "page.html").write_text(_PAGE.replace("__FIRST__", first_label), encoding="utf-8")
            result = smoke_html_artifacts(root, ["page.html"], timeout=30)
            self.assertTrue(result.attempted)
            self.assertTrue(result.ok, result.summary)
            return result.summary, dict(result.receipts[0])

    def test_a_start_control_the_press_probe_also_presses_is_counted_once(self) -> None:
        """The failing half of the pair: exercised was 7 on a 7-control page."""

        summary, receipt = self._run("Start Game")
        self.assertEqual(receipt.get("exercised_controls"), 6, receipt)
        self.assertIn("1 of 7 control(s) not exercised", summary)

    def test_the_twin_whose_first_button_is_plain_is_unchanged(self) -> None:
        """The control. Same page, same six presses, one label different.

        It reported the gap correctly before this change and must still do so,
        or the pair no longer isolates the double count.
        """

        summary, receipt = self._run("Alpha")
        self.assertEqual(receipt.get("exercised_controls"), 6, receipt)
        self.assertIn("1 of 7 control(s) not exercised", summary)

    def test_the_probe_still_presses_the_same_six_controls(self) -> None:
        """Counting honestly must not be achieved by pressing less."""

        for label in ("Alpha", "Start Game"):
            with self.subTest(first=label):
                _, receipt = self._run(label)
                self.assertEqual(receipt.get("pressed_controls"), 6, receipt)

    def test_the_exercised_count_never_exceeds_the_controls_on_the_page(self) -> None:
        """The arithmetic the clamp in web_artifact_smoke.py was hiding."""

        for label in ("Alpha", "Start Game"):
            with self.subTest(first=label):
                _, receipt = self._run(label)
                self.assertLessEqual(
                    int(receipt.get("exercised_controls") or 0),
                    int(receipt.get("interactive_count") or 0),
                    receipt,
                )
