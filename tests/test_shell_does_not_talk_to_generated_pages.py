"""Thomas's internal frame traffic must not be aimed at a generated page.

`relayFrames` posted to EVERY iframe on the page with Thomas's own origin as
the target. That was harmless while Code results were previewed with srcdoc,
which inherits this origin. They are now served from their own isolated
loopback origin, so every relay was refused by the browser and logged:

    Failed to execute 'postMessage' on 'DOMWindow': The target origin provided
    ('http://127.0.0.1:8899') does not match the recipient window's origin
    ('http://127.0.0.1:49358')

Once per preview frame, per message. The refusal is correct -- theme and
UI-edit traffic is Thomas's internal state, and a page he generated is
untrusted content with no business receiving it -- so the fix is to stop
aiming at those frames rather than to widen the target origin.
"""

from __future__ import annotations

from pathlib import Path

SHELL = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js" / "workspace_shell.js"


def _js() -> str:
    return SHELL.read_text(encoding="utf-8")


def test_relaying_skips_frames_that_are_not_ours() -> None:
    body = _js().split("function relayFrames", 1)[1].split("\n  function", 1)[0]

    assert "isOurFrame(frame)" in body


def test_theme_is_not_pushed_into_a_generated_page() -> None:
    body = _js().split("function sendTheme", 1)[1].split("\n  function", 1)[0]

    assert "isOurFrame(frame)" in body


def test_a_srcdoc_frame_still_counts_as_ours() -> None:
    """srcdoc and about:blank inherit this origin and report an empty src, so
    the existing workspace frames must keep working."""
    body = _js().split("function isOurFrame", 1)[1].split("\n  function", 1)[0]

    assert 'if (!src || src.startsWith("about:")) return true;' in body


def test_the_target_origin_was_not_widened_instead() -> None:
    """Posting with '*' would have silenced the warning by handing Thomas's
    internal messages to the generated page -- the opposite of the fix."""
    text = _js()

    assert 'postMessage(message, "*")' not in text
    assert "postMessage(message, location.origin)" in text


def test_an_unparseable_src_is_treated_as_foreign() -> None:
    """Unknown means excluded: a frame whose origin cannot be established does
    not get Thomas's internal traffic."""
    body = _js().split("function isOurFrame", 1)[1].split("\n  function", 1)[0]

    assert "return false;" in body.split("catch", 1)[1]
