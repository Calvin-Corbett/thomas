"""A run that pressed controls must not report that it touched nothing.

"boot only" is a claim about what the CHECK did, and the module says so in its
own words: "it means the page loaded and nothing on it was ever touched". Since
the press-and-observe probe landed that stopped being true. The probe presses up
to six controls and records only the ones that visibly changed the page, so a
run that pressed three and saw nothing publishes an empty ``interactions`` --
byte-identical to a run that pressed nothing at all.

MEASURED on a real deliverable, projects/"Build a single-page tip calculator in
indexhtml 3", driven by hand through playwright first to establish that the page
is correct in every respect: all five controls work, and the arithmetic checks
out against arithmetic computed independently::

    bill 87.65 @ 15% (default)  page $13.15 / $100.80   mine $13.15 / $100.80
    bill 87.65 @ 10% preset     page  $8.77 /  $96.42   mine  $8.77 /  $96.42
    bill 87.65 @ 20% preset     page $17.53 / $105.18   mine $17.53 / $105.18
    bill 42.00 @ 18% typed      page  $7.56 /  $49.56   mine  $7.56 /  $49.56

Its smoke receipt read ``pressed_controls: 3, pressed_responded: 0`` while the
summary said::

    before: index.html: browser boot clean; boot only; 2 control(s) not exercised
    after:  index.html: browser boot clean; pressed 3 control(s), none of which
            changed the page; 2 of 5 control(s) not exercised

The three presets WERE pressed. They correctly do nothing until a bill is
entered, so nothing was recorded, so the summary said nothing was touched -- and
then counted those three silent presses as exercised, leaving a bare "2" on a
five-control page. The two halves contradict each other, and the contradiction
resolves the flattering way: a reader who trusts the number concludes three of
five controls were verified. None were.

Across the 46 HTML deliverables in ~/.thomas/projects, 2 summaries claimed
"boot only" on a run that had pressed controls (the tip calculator and the
flashcards app) before the fix, and 0 after. Every other summary was unchanged.

These tests drive the real function with an injected runner rather than scanning
the source, because the sibling guards in this suite are all text scans and a
text scan cannot tell which branch a receipt actually lands in.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from thomas.forge.anvil.web_artifact_smoke import _run_one


class _FakeCompleted:
    """Just enough of `subprocess.CompletedProcess` for the smoke to read."""

    def __init__(self, stdout: str) -> None:
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


def _summary_for(tmp_path: Path, receipt: dict[str, Any]) -> str:
    """Run the real `_run_one` against a receipt the browser would have published.

    `_run_one` is used rather than `smoke_html_artifacts` on purpose: the public
    entry point returns "browser smoke unavailable" when no Chrome or Edge is
    installed, which would make every assertion below pass without executing the
    code under test.
    """

    page = tmp_path / "index.html"
    page.write_text("<html><head></head><body>hi</body></html>", encoding="utf-8")
    encoded = base64.b64encode(json.dumps(receipt).encode("utf-8")).decode("ascii")
    dom = f'<html data-thomas-smoke="{encoded}"></html>'

    def runner(*_args: object, **_kwargs: object) -> _FakeCompleted:
        return _FakeCompleted(dom)

    ok, summary, _receipt = _run_one("chrome", tmp_path, "index.html", timeout=5, runner=runner)
    assert ok, f"the fixture receipt should describe a clean boot, got {summary!r}"
    return summary


def _clean_receipt(**overrides: Any) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "dom_ready": True,
        "errors": [],
        "console_errors": [],
        "resource_errors": [],
        "interactions": [],
        "notes": [],
        "canvas": None,
        "body_text_chars": 199,
        "interactive_count": 5,
        "pressed_controls": 0,
        "pressed_responded": 0,
        "exercised_controls": 0,
    }
    receipt.update(overrides)
    return receipt


def test_a_run_that_pressed_three_controls_does_not_say_boot_only(tmp_path: Path) -> None:
    """The tip calculator's exact receipt: 3 pressed, 0 responded, 5 controls."""

    summary = _summary_for(
        tmp_path,
        _clean_receipt(pressed_controls=3, pressed_responded=0, exercised_controls=3),
    )
    assert "boot only" not in summary, (
        "the summary says 'boot only' -- which this module defines as 'the page "
        "loaded and nothing on it was ever touched' -- on a run whose own receipt "
        f"records three controls pressed. Got {summary!r}"
    )
    assert "pressed 3 control(s)" in summary, (
        f"the summary does not say how many controls it pressed. Got {summary!r}"
    )


def test_the_untouched_count_keeps_its_denominator_once_something_was_pressed(
    tmp_path: Path,
) -> None:
    """A bare "2" on a five-control page reads as near-complete coverage.

    The bare form exists for the run that drove nothing, where untouched IS the
    total and the denominator would merely repeat it. It was gated on the
    "boot only" string, so it leaked onto runs that pressed controls and got no
    response -- the runs carrying the LEAST evidence got the most flattering
    wording.
    """

    summary = _summary_for(
        tmp_path,
        _clean_receipt(pressed_controls=3, pressed_responded=0, exercised_controls=3),
    )
    assert "2 of 5 control(s) not exercised" in summary, (
        "the untouched count dropped its denominator on a run that pressed three "
        f"of five controls, so '2 not exercised' reads as 3 verified. Got {summary!r}"
    )


def test_a_run_that_really_touched_nothing_still_says_boot_only(tmp_path: Path) -> None:
    """The control, so the fix above cannot be a blanket rewording.

    Measured unchanged on the real deliverable projects/"Build a small site
    indexhtml linking to"/index.html, which has six links and no pressable
    button::

        before and after: index.html: browser boot clean; boot only;
                          6 control(s) not exercised

    Here the bare count is correct: nothing was attempted, so untouched equals
    the total and a denominator would only repeat it.
    """

    summary = _summary_for(
        tmp_path,
        _clean_receipt(interactive_count=6, pressed_controls=0, exercised_controls=0),
    )
    assert "boot only" in summary, (
        f"a run that pressed nothing no longer reports 'boot only'. Got {summary!r}"
    )
    assert "6 control(s) not exercised" in summary, (
        f"the boot-only coverage count changed shape. Got {summary!r}"
    )


def test_a_run_that_drove_the_page_still_lists_what_responded(tmp_path: Path) -> None:
    """The second control: recorded interactions must win over the press count.

    Measured unchanged on wordfreq.html, whose receipt carries both recorded
    interactions and `pressed_controls: 1`::

        before and after: wordfreq.html: browser boot clean; typed:smoke test,
                          clicked:Count words; 2 of 4 control(s) not exercised
    """

    summary = _summary_for(
        tmp_path,
        _clean_receipt(
            interactions=["typed:smoke test", "clicked:Count words"],
            interactive_count=4,
            pressed_controls=1,
            pressed_responded=0,
            exercised_controls=2,
        ),
    )
    assert "typed:smoke test, clicked:Count words" in summary, (
        f"the controls that did respond are no longer named. Got {summary!r}"
    )
    assert "pressed 1 control(s)" not in summary, (
        "the press count displaced the recorded interactions; it is the fallback "
        f"for when nothing responded, not an extra clause. Got {summary!r}"
    )
    assert "2 of 4 control(s) not exercised" in summary, (
        f"the coverage line changed on a driven run. Got {summary!r}"
    )
