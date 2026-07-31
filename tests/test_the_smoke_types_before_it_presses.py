"""Verification supplies input, then presses -- the way a person would.

The previous attempt pressed a control and reported when nothing changed. It was
reverted because it fired on three working apps out of four: the Minesweeper
reset face on a fresh board, a 10% tip preset with no bill entered, "Add task"
with an empty field. Every one of those correctly does nothing until something
else happens first.

Supplying the input removes that excuse. Measured on real deliverables before
shipping this time::

    to-do list       typed:smoke test, clicked:Add task      (was "boot only")
    kanban           typed:smoke test, clicked:Add card      (was "boot only")
    tip calculator   not driven -- more than one entry field
    expenses         nav:List, nav:Summary -- already driven, untouched
    minesweeper      not driven -- no text field; coverage count only
    habit tracker    not driven -- 29 checkboxes, no text field
    swatch           plainly "boot only" -- no controls at all

    apps wrongly reported dead: 0

Two runs that previously proved nothing now carry real evidence that the app
responds. That is the point: not catching more failures, but being able to say
something TRUE about whether the thing works.

Deliberately narrow -- exactly one text entry and a non-destructive submit-ish
control. A form needing a date format, a chosen category, or two fields is not
driven, because guessing there is what produced three wrong answers last time.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "thomas" / "forge" / "anvil" / "web_artifact_smoke_assets.py"


def _source() -> str:
    """Comments stripped: this change is documented above itself and the prose
    quotes the strings under test."""

    return "\n".join(
        line for line in ASSETS.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//") and not line.lstrip().startswith("#")
    )


def test_it_types_into_the_field_before_pressing() -> None:
    body = _source()
    assert re.search(r"dispatchEvent\(new Event\(\"input\"", body), (
        "the probe no longer dispatches an `input` event after setting the value, "
        "so a framework-bound field never sees the text and the press tests nothing"
    )
    assert "typed:" in body, (
        "the smoke no longer records what it typed, so a driven run cannot show "
        "that input was supplied before the press"
    )


def test_it_only_drives_a_single_unambiguous_field() -> None:
    """The gate that keeps the false-positive rate at zero.

    Two fields means the probe cannot know what the form wants, and filling one
    then pressing produces a wrong 'nothing changed' -- the exact failure that
    got the previous version reverted.
    """

    body = _source()
    assert re.search(r"entries\.length\s*===\s*1", body), (
        "the probe no longer requires exactly ONE entry field, so it will fill "
        "one field of a multi-field form and report a working app as dead"
    )


def test_destructive_controls_are_never_pressed() -> None:
    """This clicks something in the owner's generated app."""

    body = _source()
    match = re.search(r"submits\s*=[\s\S]{0,600}?\.filter\(\(node\) => !/\(([^)]+)\)/i", body)
    assert match, "the destructive-label exclusion on the submit control is gone"
    excluded = match.group(1)
    for word in ("delete", "clear", "reset", "erase", "discard"):
        assert word in excluded, (
            f"{word!r} is no longer excluded, so verification may destroy the "
            f"owner's data to find out whether a button works. Got: {excluded!r}"
        )


def test_the_reverted_press_only_probe_stays_reverted() -> None:
    """Pressing without supplying input is what got three working apps flagged."""

    body = _source()
    assert "pressed ${label} and nothing on the page changed" not in body, (
        "the press-without-input probe is back; it reported the Minesweeper "
        "reset face, a 10% tip preset and an empty-field 'Add task' as dead"
    )
