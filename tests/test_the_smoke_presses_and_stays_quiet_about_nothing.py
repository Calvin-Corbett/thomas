"""Verification presses controls, and reports only what actually responded.

A press probe was built once before and reverted, for a good reason recorded in
`web_artifact_smoke_assets.py`: it fired on 3 of 4 button-carrying apps and was
wrong every time -- a Minesweeper reset face on a fresh board, a 10% tip preset
with no bill entered, "Add task" with an empty field. All three correctly do
nothing until something else happens first.

The objection was about the NOTE, not the press: "a note that fires on working
apps teaches the reader to skip it, which is how a permanently-red signal ends
up hiding a real one."

So this version presses and stays silent about anything that did not change. A
control that does nothing yet produces no note and no verdict; a control that
DOES change the page produces the one thing boot-only verification could never
supply -- evidence the app responds.

Measured across the same 20 real deliverables before and after::

    driven pages   4 -> 9
    runs failed    2 -> 2      (both pre-existing: a page whose styles.css and
                                script.js are absent, and a report whose
                                sales.csv is absent -- genuine broken
                                deliverables, correctly caught before and after)

    minesweeper    boot only; 82 not exercised
                -> pressed:Hidden cell, row 1, colu; 76 of 82 not exercised
    habit tracker  boot only; 33 not exercised
                -> pressed:+Add habit, pressed:Drink enough water...
    countdown      clicked:Start  ->  clicked:Start, pressed:Pause
    palette        boot only  ->  pressed:Randomise, pressed:Coral#D13E53
    ledger         boot only  ->  pressed:Sort by amount

One hazard found by measurement and fixed before shipping: pressing
wordfreq.html's "Download CSV" -- an ordinary createObjectURL + anchor click --
left headless Chrome waiting on the transfer until the smoke hit its timeout,
returning ``ok: False, "browser smoke timed out"`` on a completely correct app.
A probe that FAILS a working deliverable is worse than one that checks nothing.
File-handing controls are skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "thomas" / "forge" / "anvil" / "web_artifact_smoke_assets.py"
SMOKE = ROOT / "thomas" / "forge" / "anvil" / "web_artifact_smoke.py"


def _strip_comments(path: Path) -> str:
    """This change is documented directly above itself and the prose quotes the
    strings under test, so a scan that reads its own comment proves nothing."""

    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//") and not line.lstrip().startswith("#")
    )


def _press_block() -> str:
    body = _strip_comments(ASSETS)
    match = re.search(r"const pressable = \[[\s\S]{0,2000}?state\.exercised_controls[^\n]*", body)
    assert match, "the press-and-observe probe is gone"
    return match.group(0)


def test_a_control_that_does_nothing_produces_no_note() -> None:
    """The whole reason the previous press probe was reverted.

    A fresh Minesweeper's reset face, an empty-field submit and an un-filled tip
    preset all correctly do nothing. If that becomes a note, the note fires on
    working apps and the reader learns to ignore it.
    """

    block = _press_block()
    assert "pushUnique(state.notes" not in block, (
        "the press probe writes a note. It must record only controls that DID "
        "change the page -- a note about a control that did nothing fires on "
        "working apps, which is exactly why the earlier version was reverted."
    )
    assert "state.interactions" in block, (
        "the press probe no longer records the controls that DID respond, so it "
        "produces no evidence at all"
    )


def test_it_never_presses_something_that_hands_over_a_file() -> None:
    """Measured: this failed a perfect app.

    wordfreq.html's "Download CSV" hung headless Chrome until the smoke timed
    out, turning a correct deliverable into `ok: False`.
    """

    block = _press_block()
    match = re.search(r"!/\(([^)]*download[^)]*)\)/i", block)
    assert match, (
        "the file-handing exclusion is gone from the press probe; pressing a "
        "download control hangs headless Chrome and fails the whole run"
    )
    excluded = match.group(1)
    for word in ("download", "export", "print"):
        assert word in excluded, f"{word!r} is no longer skipped; got {excluded!r}"


def test_destructive_controls_are_still_never_pressed() -> None:
    """This clicks buttons in the owner's generated app."""

    block = _press_block()
    match = re.search(r"!/\(([^)]*delete[^)]*)\)/i", block)
    assert match, "the destructive-label exclusion on the press probe is gone"
    excluded = match.group(1)
    for word in ("delete", "clear", "reset", "erase", "wipe"):
        assert word in excluded, (
            f"{word!r} is no longer excluded, so verification may destroy the "
            f"owner's data to find out whether a button works. Got {excluded!r}"
        )


def test_it_presses_a_bounded_number_of_controls() -> None:
    """82 controls must not mean 82 clicks and an 82x longer check."""

    block = _press_block()
    assert re.search(r"\.slice\(0,\s*\d+\)", block), (
        "the press probe no longer caps how many controls it presses"
    )


def test_the_coverage_line_still_reports_what_was_left_alone() -> None:
    """Pressing 6 of 82 must not read as though the board was checked.

    Before this probe the coverage note only appeared on a "boot only" run.
    That is now the case that needs it LEAST -- a run that drove two controls
    and says nothing about the other eighty is the misleading one.
    """

    body = _strip_comments(SMOKE)
    assert "exercised_controls" in body, (
        "the coverage line no longer subtracts the controls that were actually "
        "exercised, so it either over- or under-states what was checked"
    )
    assert re.search(r"of \{total\} control\(s\) not exercised", body), (
        "a run that drove some controls no longer reports how many it left "
        "alone; pressing 6 of 82 then printing only the successes reads as "
        "though the whole page was checked"
    )
