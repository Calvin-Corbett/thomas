"""A generated app's Copy button has to copy, and its Fullscreen key has to work.

Fifth instance of one shape, and the first where the gate is NOT a sandbox token.
The four before it (`unsafe-eval`, `allow-modals`, `allow-pointer-lock`,
`allow-downloads`) were all fixed by widening the artifact CSP sandbox and the
viewer's `sandbox` attribute. This one is a layer over: `fullscreen` and the
async clipboard are **Permissions Policy** features whose default allowlist is
``self``, so an embedding page must delegate them with ``allow=`` or a
cross-origin frame is refused. The artifact is served from its own ephemeral
``127.0.0.1:PORT``, which IS cross-origin to the shell -- and neither artifact
frame delegated anything.

Measured on two of the owner's own deliverables, unmodified, driven through
Thomas's real preview route with Chromium 145. The CONTROL is the same bytes off
the same server opened top-level, so the row can show success::

    surface                   | colortoy.html Copy button | snake.html F key
    --------------------------+---------------------------+------------------
    CONTROL: opened top-level | Copied!                   | fullscreen
    Code viewer stage         | dead (still says 'Copy')  | dead (nothing)
    Chat canvas (render)      | dead (still says 'Copy')  | dead (nothing)

and after adding ``allow="fullscreen; clipboard-write"`` to those two frames::

    CONTROL: opened top-level | Copied!                   | fullscreen
    Code viewer stage         | Copied!                   | fullscreen
    Chat canvas (render)      | Copied!                   | fullscreen

Neither failure reports anything. ``colortoy.html`` (exec-a8e034a6d778) is::

    copy.addEventListener('click', async () => {
      await navigator.clipboard.writeText(hex.textContent);
      copy.textContent = 'Copied!';
      ...

with no catch, so the rejected promise aborts the handler before the label ever
changes -- the button is inert and says nothing went wrong. ``snake.html``
(exec-e3bdee4b813b) prints "F fullscreen" on its own start screen and then
ignores the key, because ``document.documentElement.requestFullscreen()`` is
rejected with ``TypeError: Disallowed by permissions policy`` and its
``.catch(() => {})`` swallows it.

Census over the 414 generated HTML/JS files in ``~/.thomas``:
``clipboard.writeText`` 3, ``requestFullscreen`` 2, ``clipboard.readText`` 0,
``getUserMedia`` 1 (a bundled vendor chunk), ``geolocation`` 0,
``getDisplayMedia`` 0, ``window.open(`` 0.

Deliberately NOT delegated, and each for a reason: **clipboard-read** (no
generated file asks for it, and it would let a page read whatever the owner last
copied -- a password, a token), **camera / microphone / display-capture /
geolocation** (nothing asks, and they are the features with a real cost if a
generated page misuses them), and **autoplay** (nothing asks; the one hit is a
vendor bundle). The server side needed no change at all: it sends no
``Permissions-Policy`` header, which is exactly why the top-level control
succeeds -- the whole loss was at the embed.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_results.js"
CHAT_HTML = ROOT / "thomas" / "server" / "web" / "chat.html"

# Attributes only. The `allow=` list is documented in a comment directly above
# each frame and those comments quote the tokens, so a scan of raw file text
# would pass with the attribute deleted.
_VIEWER_STAGE = r"tc-code-viewer-stage\"><iframe([^>]*)>"
_CHAT_CANVAS = r"canvasState\.mode === 'render'.{0,3000}?<iframe([^>]*?)>"


def _allow(tag: str) -> str:
    match = re.search(r'allow="([^"]*)"', tag)
    return match.group(1) if match else ""


def _viewer_stage_tag() -> str:
    match = re.search(_VIEWER_STAGE, RESULTS_JS.read_text(encoding="utf-8"))
    assert match, "the Code viewer stage iframe is gone or was rewritten"
    return match.group(1)


def _chat_canvas_tag() -> str:
    match = re.search(_CHAT_CANVAS, CHAT_HTML.read_text(encoding="utf-8"), re.S)
    assert match, "Chat's canvas 'render' iframe is gone or was rewritten"
    return match.group(1)


def test_the_code_viewer_lets_an_app_copy_to_the_clipboard() -> None:
    allow = _allow(_viewer_stage_tag())
    assert "clipboard-write" in allow, (
        "the Code viewer stage does not delegate clipboard-write, so a generated "
        "Copy button is dead there: navigator.clipboard.writeText rejects with "
        "NotAllowedError and a handler that awaits it without a catch never "
        f"reaches its own success line. Got allow={allow!r}"
    )


def test_the_code_viewer_lets_a_game_go_fullscreen() -> None:
    allow = _allow(_viewer_stage_tag())
    assert "fullscreen" in allow, (
        "the Code viewer stage does not delegate fullscreen, so requestFullscreen "
        "is rejected with 'Disallowed by permissions policy' and a generated "
        f"game's Fullscreen key does nothing. Got allow={allow!r}"
    )


def test_chats_canvas_gets_the_same_two_capabilities() -> None:
    """Chat opens a playable result on the Canvas automatically; it is a use surface.

    The completion announcement calls `canvasRender` for any artifact of kind
    'web' or named *.html, so this frame is where the owner meets a generated app
    in Chat -- the counterpart of Code's viewer stage, and it was measured just as
    dead.
    """

    allow = _allow(_chat_canvas_tag())
    assert "clipboard-write" in allow and "fullscreen" in allow, (
        "Chat's canvas frame does not delegate fullscreen/clipboard-write, so the "
        "app that pops open there when Thomas says 'here it is' still has a dead "
        f"Copy button and a dead Fullscreen key. Got allow={allow!r}"
    )


def test_the_decorative_previews_cannot_fill_the_screen_or_read_the_clipboard() -> None:
    """A 168px `tabindex="-1"` picture must not be able to take over the display.

    Measured after the change, driving snake.html's F key through each frame's own
    attributes: both still report `refused`, because Permissions Policy is
    delegated per embed and these embeds delegate nothing.
    """

    js = RESULTS_JS.read_text(encoding="utf-8")
    offenders = []
    for cls in ("tc-code-artifact-thumb", "tc-code-artifact-shot"):
        for match in re.finditer(re.escape(cls) + r".{0,300}?<iframe([^>]*)>", js, re.S):
            allow = _allow(match.group(1))
            if allow:
                offenders.append(f"{cls}: allow={allow!r}")
    assert not offenders, (
        "a decorative, non-interactive preview can now use a delegated capability; "
        "these frames are never clicked and must stay inert:\n  " + "\n  ".join(offenders)
    )


def test_only_what_a_generated_app_was_measured_needing_is_delegated() -> None:
    """The discipline half: widen for a measured defect, never speculatively.

    clipboard-READ is the one that matters -- it would hand a generated page
    whatever the owner last copied. No generated file calls `clipboard.readText`
    or `clipboard.read(`; 3 call `writeText`.
    """

    forbidden = ("clipboard-read", "camera", "microphone", "geolocation", "display-capture")
    for label, tag in (("Code viewer stage", _viewer_stage_tag()), ("Chat canvas", _chat_canvas_tag())):
        allow = _allow(tag)
        for feature in forbidden:
            assert feature not in allow, (
                f"{label} now delegates {feature!r}, which no generated deliverable "
                f"was measured needing. Got allow={allow!r}"
            )
