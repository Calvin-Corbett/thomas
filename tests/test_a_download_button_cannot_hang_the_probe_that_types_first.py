"""A download control fails a working app, and BOTH clicking probes must skip it.

`web_artifact_smoke_assets.py` runs two probes that click, in this order:

1. type-then-press -- fills the page's one text field and presses ``submits[0]``
2. press-and-observe -- presses up to six controls and records the responders

The press-and-observe probe was built with a file-handing exclusion, and its own
comment records why: pressing wordfreq.html's "Download CSV" (an ordinary
``createObjectURL`` + anchor click) leaves headless Chrome waiting on the
transfer until the smoke hits its timeout, so a completely correct deliverable
comes back ``ok: False, "browser smoke timed out"``.

The type-then-press probe never got that exclusion -- and it clicks FIRST, and
picks ``submits[0]``, which is document order. So a page that writes its download
button before its real one was failed by the guard's own named hazard, one block
above the guard.

Measured with the real headless-Chrome smoke, same Download CSV handler in every
fixture, varying only which probe could reach it.  "before" is the harness string
read straight out of commit de100601; nothing else differed between the runs::

                                              before                     after
    textarea, Download CSV first    ok False  timed out 21.4s   ok True  2.9s
                                                                typed:smoke test,
                                                                clicked:Count words;
                                                                1 of 3 not exercised
    textarea, Download CSV only     ok False  timed out 20.5s   ok True  1.5s
                                                                boot only;
                                                                2 control(s) not exercised

Three controls answer "could this have shown success if the thing worked?" --
each was ``ok True`` on the pre-fix harness too, so the two failures above are
attributable to the probe and not to the fixtures::

    textarea, Count words first     ok True 1.5s -> ok True 1.7s   (unchanged)
    to-do form, no download button  ok True 3.3s -> ok True 1.4s   (unchanged)
    Download CSV but no text field  ok True 2.1s -> ok True 3.2s   (unchanged)

The last control is the sharp one: the identical button is harmless when only the
press probe can reach it, because that probe already skips it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "thomas" / "forge" / "anvil" / "web_artifact_smoke_assets.py"

_FILE_HANDING = re.compile(r"!/\(([^)]*download[^)]*)\)/i")


def _strip_comments(text: str) -> str:
    """The fix is documented directly above itself and the prose quotes the
    strings under test, so a scan that reads its own comment proves nothing."""

    return "\n".join(
        line
        for line in text.splitlines()
        if not line.lstrip().startswith("//") and not line.lstrip().startswith("#")
    )


def _block(pattern: str, why: str) -> str:
    match = re.search(pattern, _strip_comments(ASSETS.read_text(encoding="utf-8")))
    assert match, why
    return match.group(0)


def _typed_probe() -> str:
    return _block(
        r"const submits = \[[\s\S]{0,3500}?raised an error",
        "the type-then-press probe is gone",
    )


def _press_probe() -> str:
    return _block(
        r"const pressable = \[[\s\S]{0,2500}?state\.exercised_controls",
        "the press-and-observe probe is gone",
    )


def test_the_probe_that_types_first_never_presses_a_download_control() -> None:
    """Measured: this failed two perfect apps by timing the whole smoke out."""

    match = _FILE_HANDING.search(_typed_probe())
    assert match, (
        "the type-then-press probe has no file-handing exclusion. It clicks "
        "before the press probe and picks submits[0] in document order, so a "
        "page whose download button comes first hangs headless Chrome until the "
        "smoke times out and a correct deliverable is reported ok: False"
    )
    excluded = match.group(1)
    for word in ("download", "export", "print"):
        assert word in excluded, f"{word!r} is no longer skipped; got {excluded!r}"


def test_both_clicking_probes_skip_exactly_the_same_file_handing_labels() -> None:
    """Guarding one call site and not the other is how this got through.

    The hazard was known, written down, and fixed in the press probe while the
    probe one block above it kept pressing the same buttons.
    """

    typed = _FILE_HANDING.search(_typed_probe())
    pressed = _FILE_HANDING.search(_press_probe())
    assert typed and pressed, "a clicking probe lost its file-handing exclusion"
    assert typed.group(1) == pressed.group(1), (
        "the two clicking probes now skip different file-handing labels, so one "
        "of them can press a control the other knows hangs the browser:\n"
        f"  type-then-press : {typed.group(1)!r}\n"
        f"  press-and-observe: {pressed.group(1)!r}"
    )


def test_skipping_the_download_does_not_stop_the_probe_driving_the_page() -> None:
    """The fix must skip one control, not disable the probe.

    Measured after the fix: the Download-CSV-first page picks the next candidate
    and reports `typed:smoke test, clicked:Count words` -- byte-identical to the
    control page that lists the same buttons the other way round.
    """

    typed = _typed_probe()
    assert "submits.length >= 1" in typed, (
        "the type-then-press probe no longer requires a surviving submit-ish "
        "control, so the exclusion above either fires on nothing or the probe "
        "reaches into an empty list"
    )
    assert "submits[0]" in typed, "the probe no longer falls back to the first surviving control"
