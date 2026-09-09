"""Opening a Code conversation must land on the newest turn, not the oldest.

A transcript that overflows its surface opened at `scrollTop: 0`, so the run
report -- the newest thing on the page and the entire answer to "did it work" --
sat below the fold and had to be hunted for. Measured on a real conversation
before the fix: 702px of unscrolled overflow with the verdict card at y=1419
inside an 868px scroller, identical via the sidebar click and via
`/?forge_code=<id>`. After: `scrollTop` 702, `fromBottom` 0, card at y=717 and
visible, on all four paths.

Short transcripts were already correct because `margin-top: auto` pins them to
the bottom of the scroller -- which is exactly why this only bit long
conversations and went unnoticed.

HONEST SCOPE: these are source-contract assertions, in the same style as
`test_the_run_report_escapes_what_thomas_wrote.py`, because the behaviour needs
the live shell, a real conversation and a browser to observe. They catch the call
being dropped in a refactor, which is the realistic regression. They would NOT
catch the scroll being defeated by a stylesheet change -- that was verified by
measurement in the browser, and re-verifying it needs the same.
"""

from __future__ import annotations

from pathlib import Path

CODE_JS = (
    Path(__file__).resolve().parents[1]
    / "thomas" / "server" / "web" / "js" / "unified_code_mode.js"
)


def _source() -> str:
    return CODE_JS.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    src = _source()
    assert f"function {name}(" in src, f"{name} is gone"
    body = src.split(f"function {name}(", 1)[1]
    return body.split("\n  function ", 1)[0]


def test_the_scroller_jumps_to_the_bottom() -> None:
    body = _function_body("scrollTranscriptToNewest")

    assert "scrollTop" in body and "scrollHeight" in body
    assert "transcriptScroller" in body, (
        "must use the shared scroller lookup -- the transcript is not always the "
        "element that scrolls, the layout can be"
    )


def test_it_jumps_again_on_the_next_frame() -> None:
    """An artifact thumbnail hydrates asynchronously and grows the transcript
    under the first jump. Dropping the second one leaves the newest turn just
    short of the bottom -- the same bug, quieter."""
    body = _function_body("scrollTranscriptToNewest")

    assert "requestAnimationFrame" in body


def test_loading_a_conversation_scrolls_immediately_and_after_hydration() -> None:
    """Both call sites, asserted separately.

    An earlier version of this test only checked that the name appeared somewhere
    in `loadConversation`. Deleting the immediate call left the one inside the
    thumbnail `.then()`, so the assertion still passed AND the browser still
    scrolled -- the fix survived being reverted. Distinguishing the two sites is
    the whole point: the immediate jump is what stops the transcript being
    painted at the top and then yanked once thumbnails resolve.
    """
    body = _function_body("loadConversation")
    before, _, after = body.partition("hydrateArtifactThumbnails")

    assert "scrollTranscriptToNewest()" in before, (
        "no immediate scroll after render -- a long transcript paints at the top "
        "and only jumps once thumbnails hydrate"
    )
    assert "scrollTranscriptToNewest()" in after[:400], (
        "no scroll after thumbnails hydrate -- a preview that resolves late grows "
        "the transcript and leaves the newest turn off the bottom"
    )
    assert body.count("scrollTranscriptToNewest()") >= 2


def test_an_internal_reload_does_not_yank_the_scroller() -> None:
    """`internal` reloads happen underneath a live run. Scrolling then would
    fight someone reading back through the transcript."""
    body = _function_body("loadConversation")

    for line in body.splitlines():
        if "scrollTranscriptToNewest()" in line:
            assert "!internal" in line, (
                f"unguarded scroll during an internal reload: {line.strip()!r}"
            )


def test_removing_either_call_site_is_caught() -> None:
    """Pins the test above against its own earlier weakness: each call site must
    be independently required, so deleting one cannot be masked by the other."""
    body = _function_body("loadConversation")
    before, _, after = body.partition("hydrateArtifactThumbnails")

    assert "scrollTranscriptToNewest()" in before
    assert "scrollTranscriptToNewest()" in after[:400]
