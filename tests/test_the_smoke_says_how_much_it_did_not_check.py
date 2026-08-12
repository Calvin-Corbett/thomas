"""A "boot only" pass must say how much of the page it never touched.

`browser boot clean; boot only` reads as "checked". It means the opposite: the
page loaded and nothing on it was ever touched. Measured across 57 recorded
runs, 29 (51%) ended that way, and among them:

    index.html   9x9 Minesweeper          82 controls, none pressed
    index.html   "the future of calculator apps"
    index.html   tip calculator            5 controls, none pressed
    tasks.html   to-do list                4 controls, none pressed

The to-do list is the sharp one: among those four untouched controls was an
Export CSV button that produced no file at all. The smoke booted the page,
reported it clean, and never pressed it.

`interactive_count` was already published on every receipt and surfaced
NOWHERE, so reporting it costs nothing and invents nothing.

This states COVERAGE, not a verdict. The page is not accused; the reader is told
how thin the evidence is. That distinction is the whole design:

Clicking one control was built and run against the real deliverables first, and
reverted. It fired on three of four button-carrying apps and was wrong every
time -- the Minesweeper reset face on a fresh board, a 10% preset with no bill
entered, "Add task" with an empty field. Each correctly does nothing until
something else happens first, and a note that fires on working apps teaches the
reader to skip it. The last two tests here pin the two ways this could go wrong
in that direction.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "thomas" / "forge" / "anvil" / "web_artifact_smoke.py"
ASSETS = ROOT / "thomas" / "forge" / "anvil" / "web_artifact_smoke_assets.py"


def _source(path: Path) -> str:
    """File text with comment lines removed.

    The change is documented directly above itself and the prose quotes the
    exact strings under test, so a scan that reads its own comment would pass
    with the code deleted -- which is how three earlier guards in this suite
    stayed green against reverted fixes.
    """

    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#") and not line.lstrip().startswith("//")
    )


def test_a_boot_only_pass_reports_the_controls_it_never_touched() -> None:
    body = _source(SMOKE)
    assert "not exercised" in body, (
        "a boot-only pass no longer says how many controls it left untouched, so "
        "'browser boot clean; boot only' again reads as 'checked' for a page like "
        "the 82-control Minesweeper"
    )
    assert "interactive_count" in body, (
        "the coverage count no longer reads `interactive_count` from the receipt; "
        "if it is computing its own number it may disagree with the receipt"
    )


def test_the_count_is_only_added_when_nothing_was_driven() -> None:
    """A run that DID drive the app must not be told what it missed.

    The calculator run records `nav:Conversions, nav:Graph studio, ...`; adding
    "N not exercised" there would bury the fact that navigation was exercised.
    """

    body = _source(SMOKE)
    assert re.search(r'interactions\s*==\s*["\']boot only["\']', body), (
        "the coverage note is no longer gated on `interactions == 'boot only'`, "
        "so it will also fire on runs that genuinely drove the page"
    )


def test_a_page_with_no_controls_gets_no_note() -> None:
    """No false noise on a static page.

    `swatch.html` has zero buttons; its summary must stay plainly 'boot only'.
    """

    body = _source(SMOKE)
    assert re.search(r"untouched\s*>\s*0", body), (
        "the coverage note is no longer gated on there being controls at all, so "
        "a static page with nothing to click now reports '0 control(s) not "
        "exercised' and reads as though something is missing"
    )


def test_the_reverted_clicking_probe_stays_reverted() -> None:
    """It fired on three working apps out of four.

    Pressing a control and reporting that nothing changed is wrong whenever the
    control needs input first, which is most of them. If this comes back it must
    SOLVE that, not just exclude destructive labels by name.

    Pinned to the exact reverted wording, not to the phrase "nothing on the page
    changed". This test originally forbade that phrase outright and promptly went
    red against the type-then-press probe -- the correct successor, which supplies
    input first and legitimately reports the same outcome. A guard that fails on
    the fix is the permanently-red test this suite exists to prevent, and it took
    about an hour to author one.
    """

    assets = _source(ASSETS)
    assert "pressed ${label} and nothing on the page changed" not in assets, (
        "the press-WITHOUT-INPUT probe is back. It reported the Minesweeper reset "
        "face, a 10% tip preset and an empty-field 'Add task' as dead pages. A "
        "note that fires on working apps trains the reader to ignore it. Supplying "
        "input first (see test_the_smoke_types_before_it_presses.py) is the "
        "version that measured zero false positives"
    )
