"""Verification only says the keyboard worked when the keyboard is what worked.

The smoke sent ArrowRight at the canvas, waited 60ms, and if the page looked
different it published ``keyboard:ArrowRight`` -- which a reader takes as "the
app responds to the arrow keys". Nothing established that the key was the cause.
Two ordinary things move a page inside those 60ms: a canvas with an animation
loop redraws every frame, and the sibling nav/type/press probes run
synchronously between the baseline snapshot and the deferred comparison, so
their clicks land inside the window being attributed to the key.

MEASURED by sending the key to a detached ``<div>`` the page can never receive,
everything else byte-identical, across 10 real deliverables under
``~/.thomas``. On the 5 that claimed an input response, the deaf run claimed
exactly the same thing -- real == deaf on every one, so not one claim was caused
by the input::

    expenses.html      keyboard:ArrowRight              real == deaf
    snake.html         keyboard:ArrowRight              real == deaf
    star-catcher.html  keyboard:ArrowRight              real == deaf
    pacman.html        keyboard:ArrowRight              real == deaf
    exec-5d2d398f3eb3  keyboard:ArrowRight, pointer:canvas   real == deaf

    input claim survived the deaf control on   5/10   before
                                               0/10   after

expenses.html is the plainest case. Driven by hand it is entirely correct --
three expenses entered give TOTAL $46.25, Food $22.85, Travel $23.40, matching
arithmetic done independently -- and it is deaf to arrows: no key handler
reacts, and a real ``keyboard.press("ArrowRight")`` changes nothing. Its summary
still read::

    browser boot clean; nav:List, nav:Summary, pressed:Add, pressed:List,
    pressed:Summary, keyboard:ArrowRight; 5 of 9 control(s) not exercised

The ``keyboard:ArrowRight`` there was the tab clicks.

The fix spends one identical idle window with no input first. If the page moved
by itself, a later difference proves nothing and nothing is claimed. On the four
pages below, whose right answer is known in advance::

    responds to ArrowRight                 True  -> True    (kept)
    ignores ArrowRight                     False -> False
    repaints on its own, no input          True  -> False   (fixed)
    deaf, but siblings click its buttons   True  -> False   (fixed)

Declining is silent on purpose. A note that fires on every animating game is the
permanently-red signal that ``web_artifact_smoke_assets.py`` already warns about
in its press-probe comment.
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
  ctx.fillStyle = '#123456'; ctx.fillRect(0, 0, 240, 160);
  __BODY__
</script>
</body></html>
"""

# Genuinely steers on ArrowRight, and nothing else on the page moves.
_RESPONDS = """
  let x = 10;
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight') { x += 40; ctx.fillStyle = '#eeddaa'; ctx.fillRect(x, 60, 30, 30); }
  });
"""

# Listens for keys, but not for this one.
_IGNORES = """
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter') { ctx.fillRect(0, 0, 5, 5); } });
"""

# An animating game: repaints on a timer, with no input at all.
_SELF_CHANGING = """
  document.addEventListener('keydown', () => {});
  let n = 0;
  setInterval(() => { n += 7; ctx.fillStyle = 'rgb(' + (n % 255) + ',10,10)'; ctx.fillRect(5, 5, 50, 50); }, 16);
"""

# The expenses.html shape: deaf to the key, but carrying buttons that the sibling
# press probe clicks synchronously inside the window attributed to the key.
_CLICKED_BY_SIBLING = """
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter') { ctx.fillRect(0, 0, 5, 5); } });
  const out = document.createElement('p');
  out.textContent = 'idle';
  document.body.appendChild(out);
  for (const name of ['Alpha', 'Beta', 'Gamma']) {
    const b = document.createElement('button');
    b.textContent = name;
    b.onclick = () => { out.textContent = 'showing ' + name; };
    document.body.appendChild(b);
  }
"""


@unittest.skipIf(_browser_executable() is None, "no Chrome or Edge available for a real smoke run")
class TestTheKeyboardClaimNamesACause(unittest.TestCase):
    def _keyboard_claims(self, body: str) -> list[str]:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "page.html").write_text(_PAGE.replace("__BODY__", body), encoding="utf-8")
            result = smoke_html_artifacts(root, ["page.html"], timeout=30)
            self.assertTrue(result.attempted)
            self.assertTrue(result.ok, result.summary)
            receipt = result.receipts[0]
            return [str(value) for value in receipt.get("interactions") or [] if str(value).startswith("keyboard:")]

    def test_a_page_that_really_steers_on_the_arrow_key_is_still_credited(self) -> None:
        """The check must not be deleted, only made to name a cause."""

        self.assertEqual(self._keyboard_claims(_RESPONDS), ["keyboard:ArrowRight"])

    def test_a_page_that_ignores_the_arrow_key_is_not_credited(self) -> None:
        self.assertEqual(self._keyboard_claims(_IGNORES), [])

    def test_a_page_that_repaints_on_its_own_is_not_credited(self) -> None:
        """This is one of the two cases that used to pass. It is half the point.

        An animating canvas hashes differently 60ms later whatever you send it,
        so the difference was never evidence about the key.
        """

        self.assertEqual(self._keyboard_claims(_SELF_CHANGING), [])

    def test_a_page_whose_own_buttons_the_probe_clicks_is_not_credited(self) -> None:
        """The other case that used to pass, and the real-world one.

        expenses.html is deaf to arrows and entirely correct by hand, yet the
        summary listed ``keyboard:ArrowRight`` next to the tab clicks that
        actually caused the change.
        """

        self.assertEqual(self._keyboard_claims(_CLICKED_BY_SIBLING), [])

    def test_the_claim_is_gated_on_an_idle_control_window(self) -> None:
        """Guards the mechanism, so a later edit cannot quietly drop the control.

        A rewrite that keeps the four cases above passing by some other honest
        means is fine; one that removes the gate is what this catches.
        """

        source = (
            Path(__file__).resolve().parents[1] / "thomas" / "forge" / "anvil" / "web_artifact_smoke_assets.py"
        ).read_text(encoding="utf-8")
        body = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith(("//", "#"))
        )
        self.assertIn("selfChanging", body, "the idle control window is gone from the input probe")
        for claim in ('state.interactions.push("keyboard:ArrowRight")', 'state.interactions.push("pointer:canvas")'):
            index = body.find(claim)
            self.assertGreater(index, 0, f"{claim} is gone")
            guard = body.rfind("if (", 0, index)
            self.assertIn(
                "!selfChanging",
                body[guard:index],
                f"{claim} is published without checking whether the page was already changing on its own",
            )


if __name__ == "__main__":
    unittest.main()
