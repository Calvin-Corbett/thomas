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

The src test alone did not finish the job. A frame sandboxed WITHOUT
allow-same-origin has an opaque origin ("null") however its content arrived,
and a srcdoc frame reports an empty src -- so Chat's live canvas frames and
Build's file-preview shot all read as ours and drew the same refusal, on the
two surfaces most likely to have a preview open while a theme changes.
`isOurFrame` reads the sandbox attribute for that, matching the token whole.

tests/web_node/shell_frame_relay.mjs runs the function against fake frames;
the checks here pin the source so the reasoning cannot be edited away.
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
    """An UNSANDBOXED srcdoc or about:blank frame does inherit this origin and
    reports an empty src, so the workspace frames must keep working. The
    sandbox check above is what separates those from the opaque previews."""
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


def test_a_sandboxed_preview_is_foreign_however_it_was_loaded() -> None:
    """The src test cannot see this one. A sandbox without allow-same-origin
    gives the document an opaque origin, so a srcdoc preview reports an empty
    src -- reading as ours -- while the browser refuses every post to it."""
    body = _js().split("function isOurFrame", 1)[1].split("\n  function", 1)[0]

    assert 'frame.getAttribute("sandbox")' in body
    assert "allow-same-origin" in body


def test_the_sandbox_token_is_matched_whole() -> None:
    """A substring test would read `allow-same-origin-please` as the real
    token and put Thomas's internal state back into an opaque frame."""
    body = _js().split("function isOurFrame", 1)[1].split("\n  function", 1)[0]

    assert 'sandbox.includes("allow-same-origin")' not in body


def test_one_refused_frame_does_not_drop_the_others() -> None:
    """The posts run inside a forEach, so an uncaught throw on one frame
    abandons every frame after it in document order."""
    body = _js().split("function postToFrame", 1)[1].split("\n  function", 1)[0]

    assert "try {" in body
    assert "return false;" in body.split("catch", 1)[1]
