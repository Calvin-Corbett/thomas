"""Thomas's own sentence about a finished job is not overwritten by a filter.

The completion bubble is model-authored. Two filters used to run over it and
replace the whole note on a match, and both resolved toward the cheerful claim:

  * a regex for "unsupported gap claims" matched ordinary honest English --
    "still needs to", "not yet", "isn't complete". It was meant to catch a
    fabricated gap. But a fabricated gap and a real one read identically, and
    "verified" upstream never meant "everything asked for was produced" --
    chat_delegation_artifact_verification.py opens with `del prompt` and only
    checks that the files that were made are real. So a run that produced two of
    three requested files and said so truthfully had that sentence deleted and was
    announced as "I have a verified result ready."

  * a check that every artifact filename appeared verbatim, while the same prompt
    asks for "one or two short sentences". Past about three files those cannot
    both be satisfied, and a live-repo run lists every changed file.

Both are gone. An absent note still falls back to a template, because there is
nothing to preserve; a note that merely reads badly is still Thomas's.
"""

from __future__ import annotations

import re
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "thomas" / "server" / "routes" / "chat_v2_announcements.py"
).read_text(encoding="utf-8")


def _announce_body() -> str:
    """The stretch that decides what the user is told, comments stripped.

    Comments are removed because this file documents the old behaviour verbatim
    in order to explain why it left -- a substring check that read the prose would
    match the explanation and pass while the code was back.
    """

    body = SOURCE.split("note = await _generate_note", 1)[1].split("strip_sandbox_links", 1)[0]
    return "\n".join(
        line for line in body.splitlines() if not line.strip().startswith("#")
    )


def test_an_honest_gap_is_not_replaced_by_a_verified_result_claim() -> None:
    body = _announce_body()

    assert "_UNSUPPORTED_GAP_CLAIM_RE" not in body, (
        "the gap filter is back: a run that truthfully reports it produced 2 of 3 "
        "files will be announced as a verified result instead"
    )
    assert "if not note:" in body, "an absent note is the only case that may fall back to a template"


def test_a_note_that_does_not_recite_filenames_is_added_to_not_discarded() -> None:
    body = _announce_body()

    assert "missing_name" not in body, "the verbatim-filename filter is back"
    # The names are still worth having; they must be appended, not substituted.
    assert "note.rstrip()" in body and "Ready:" in body, (
        "artifact names are no longer appended, so naming the files was lost entirely "
        "rather than made non-destructive"
    )


def test_a_dark_mode_toggle_is_not_mistaken_for_a_physical_device() -> None:
    """The device group had a trailing `?`, so the bare word matched."""

    from thomas.server.routes.chat_v2_announcements import _DEVICE_ACTION_RE

    for benign in (
        "Add a dark mode toggle to the site",
        "Build a settings page with a toggle for notifications",
    ):
        assert not _DEVICE_ACTION_RE.search(benign), (
            f"{benign!r} reads as a real-world device action, so shipping app.js makes "
            "Thomas announce the work was NOT done"
        )


def test_the_real_device_case_still_works() -> None:
    """The control. Narrowing the pattern must not un-fix the bug it was added for:
    a run that ships a control script for "turn off the kitchen lights" has to keep
    saying the lights were not actually touched."""

    from thomas.server.routes.chat_v2_announcements import _DEVICE_ACTION_RE

    for real in (
        "turn off the kitchen lights",
        "set my bedroom thermostat to 68",
        "toggle the garage door",
        "unlock the front door",
    ):
        assert _DEVICE_ACTION_RE.search(real), f"{real!r} no longer reads as a device action"


def test_the_device_pattern_still_has_a_bare_verb_alternation() -> None:
    """Documents what was NOT fixed, so it is not mistaken for done.

    The last alternation is a list of bare verbs with no target requirement at all:
    play, pause, send, text, email, call, schedule, book, order, pay, transfer. A
    title like "Build a music player with play/pause" matches on `play`, and since
    the script test accepts .js/.py/.json almost any coding deliverable qualifies.
    Narrowing it needs its own pass with real titles; this pins the fact that the
    hazard is still there rather than letting it read as handled.
    """

    from thomas.server.routes.chat_v2_announcements import _DEVICE_ACTION_RE, _SCRIPT_ARTIFACT_RE

    assert _DEVICE_ACTION_RE.search("Build a music player with play/pause controls")
    assert _SCRIPT_ARTIFACT_RE.search("app.js")
    assert re.search(r"play\|pause\|send", SOURCE), "the bare-verb list moved; re-check this note"
