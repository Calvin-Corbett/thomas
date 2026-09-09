"""A deliverable made of several files must load its own files.

Thomas builds plenty of apps as ``index.html`` + ``styles.css`` + ``game.js``.
The Code viewer stage -- the panel that opens beside the chat, and the main way
anyone looks at a result -- framed them without ``allow-same-origin``. The
document then has an OPAQUE origin, so ``default-src 'self'`` matches nothing
and every relative subresource is refused.

The owner saw an unstyled wall of Times New Roman over a dead 300x150 canvas,
while the little thumbnail beside it and the same file in a new tab both showed
the finished app.

Isolated on a standalone page that never re-renders, after a 9s settle, so an
aborted re-render could not be the explanation::

    without allow-same-origin      with it
    window.origin  'null'          real origin
    cssRules       SecurityError   154
    fetch(styles)  TypeError       200
    font           Times New Roman "Barlow Condensed"
    canvas         300x150         1280x800

Chromium reports those refusals as ``net::ERR_ABORTED``, not ``csp``, which
reads like a cancelled request and is exactly why this looked like a rendering
race. And read ``window.origin``, never ``location.origin``: the latter returns
the URL's origin even in an opaque document, and says "not opaque" when it is.

The two decorative previews already carried the token; the interactive stage was
the only frame without it -- the same "every sibling but one" shape as
``project_delta_since`` and ``--c-danger``.

Safe because the artifact is served from its OWN port, a different origin from
the shell, so the frame cannot reach Thomas's DOM or cookies; and the response
CSP already grants the same token at the sandbox layer, so this only stops the
iframe attribute from being stricter than the policy intends.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_results.js"

# Every frame that renders a generated deliverable, and what it is for.
DELIVERABLE_FRAMES = {
    "tc-code-viewer-stage": "the panel the owner actually uses the app in",
    "tc-code-artifact-thumb": "the transcript thumbnail",
    "tc-code-artifact-shot": "the drawer preview",
}


def _sandbox_for(marker: str) -> str | None:
    js = RESULTS_JS.read_text(encoding="utf-8")
    # Comments are skipped: this fix is documented directly above itself and the
    # documentation names the tokens, so a scan that reads its own comment would
    # pass with the attribute deleted.
    without_comments = re.sub(r"<!--.*?-->", "", js, flags=re.S)
    match = re.search(re.escape(marker) + r".{0,260}?sandbox=\"([^\"]*)\"", without_comments, re.S)
    return match.group(1) if match else None


def test_every_surface_that_shows_a_deliverable_can_load_its_files() -> None:
    missing = []
    for marker, what in DELIVERABLE_FRAMES.items():
        sandbox = _sandbox_for(marker)
        if sandbox is None:
            missing.append(f"{marker} ({what}): no sandbox attribute found at all")
        elif "allow-same-origin" not in sandbox:
            missing.append(f"{marker} ({what}): {sandbox!r}")

    assert not missing, (
        "a surface that renders a generated deliverable cannot load the "
        "deliverable's own styles.css / game.js: without allow-same-origin the "
        "document has an opaque origin and default-src 'self' matches nothing, "
        "so it renders as unstyled markup over a dead canvas:\n  "
        + "\n  ".join(missing)
    )


def test_the_stage_still_carries_the_other_tokens() -> None:
    """Guards against a rewrite that fixes assets and drops the rest.

    Each of these was its own measured defect: modals (dead confirm buttons),
    pointer lock (an FPS that could not turn), downloads (an Export button that
    produced nothing).
    """

    sandbox = _sandbox_for("tc-code-viewer-stage")
    assert sandbox, "the viewer stage iframe has no sandbox attribute"
    for token in ("allow-scripts", "allow-forms", "allow-modals",
                  "allow-pointer-lock", "allow-downloads"):
        assert token in sandbox, (
            f"the viewer stage lost {token!r}, which was added for a measured "
            f"defect. Got: {sandbox!r}"
        )


def test_the_stage_is_not_granted_top_navigation() -> None:
    """The line this must not cross.

    allow-same-origin is safe because the artifact lives on its own port, a
    different origin from the shell. Letting the frame navigate the top-level
    document would hand a generated page control of the whole window, which no
    deliverable needs.
    """

    sandbox = _sandbox_for("tc-code-viewer-stage") or ""
    for token in ("allow-top-navigation", "allow-popups-to-escape-sandbox",
                  "allow-modals-to-escape", "allow-presentation"):
        assert token not in sandbox, (
            f"the viewer stage was granted {token!r}; no generated deliverable "
            f"needs it and it widens the sandbox past containment. Got: {sandbox!r}"
        )
