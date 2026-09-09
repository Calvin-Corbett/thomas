"""A generated first-person game has to be able to look around.

From a game Thomas built on 2026-07-30
(``~/.thomas/projects/Code task 2026-07-30 1137/game.js``)::

    canvas.addEventListener('mousedown', (event) => {
      ...
      if (document.pointerLockElement !== canvas) canvas.requestPointerLock?.();
      state.shooting = true; shoot();
    });
    addEventListener('mousemove', (event) => {
      if (state.phase === 'playing' && document.pointerLockElement === canvas && state.player)
        state.player.angle += event.movementX * .0023;
    });

Mouse-look is gated entirely on ``pointerLockElement === canvas``. The artifact
CSP sandbox did not grant ``allow-pointer-lock``, so that is never true: the
player can shoot but cannot TURN. Nothing is raised; the request is refused
silently. Two of the owner's own deliverables call ``requestPointerLock`` (that
game.js and ``code_scratch/blocktown-84.html``).

Third instance of one shape, all found the same way -- by using the app rather
than by a failing test:

    'unsafe-eval' missing      a correct calculator printed "Error"
    allow-modals missing       every confirm-before-delete button was dead
    allow-pointer-lock missing an FPS could not turn around

Verified live, with a control, because pointer lock also needs a user gesture
and may not engage headless -- so a bare "BLOCKED" could have meant any of three
things:

    control (Thomas shell, unsandboxed)   LOCKED   <- so the mechanism works here
    artifact, top level                   LOCKED
    viewer stage                          LOCKED
    transcript thumbnail                  BLOCKED  <- ceiling raised, still refused

``allow-popups`` is deliberately NOT granted: no deliverable calls
``window.open(``, so there is nothing to fix and no reason to widen the sandbox.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELIVERABLE = ROOT / "thomas" / "server" / "routes" / "deliverable_aiohttp.py"
RESULTS_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_results.js"


def _served_sandbox() -> str:
    """The CSP sandbox directive for the artifact preview, comments stripped.

    Comments first: this directive is documented immediately above itself and the
    documentation quotes it, so a scan that reads its own comment would pass with
    the change deleted.
    """

    text = DELIVERABLE.read_text(encoding="utf-8")
    without_comments = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    # Join adjacent string literals before scanning. The directive outgrew one
    # line and Python implicitly concatenates `"sandbox a b "` `"c d; "`, which
    # made this guard fail with the token PRESENT -- it had captured only up to
    # the first closing quote. A guard that goes red on reformatting is a guard
    # that gets ignored, which is how a real regression slips past.
    joined = re.sub(r'"\s*\n\s*"', "", without_comments)
    directives = [m.group(1) for m in re.finditer(r'"sandbox ([^";]*)', joined)]
    served = [d for d in directives if "allow-same-origin" in d]
    assert served, "no artifact sandbox directive grants allow-same-origin any more"
    return served[0]


def test_the_artifact_csp_permits_pointer_lock() -> None:
    directive = _served_sandbox()
    assert "allow-pointer-lock" in directive, (
        "the artifact CSP sandbox omits allow-pointer-lock, so a generated "
        "first-person game cannot capture the mouse: mouse-look is gated on "
        "`document.pointerLockElement === canvas`, which can never be true. The "
        f"player can shoot but not turn. Got: {directive!r}"
    )


def test_the_viewer_stage_opts_in_to_pointer_lock() -> None:
    js = RESULTS_JS.read_text(encoding="utf-8")
    stage = re.search(r"tc-code-viewer-stage.{0,200}?sandbox=\"([^\"]*)\"", js, re.S)
    assert stage, "the viewer stage iframe is gone or no longer carries a sandbox attribute"
    assert "allow-pointer-lock" in stage.group(1), (
        "the viewer stage -- where the owner actually plays -- does not allow "
        f"pointer lock, so mouse-look is still dead there. Got: {stage.group(1)!r}"
    )


def test_the_decorative_previews_cannot_swallow_the_cursor() -> None:
    """A 168px picture must never capture the mouse.

    Measured after the change: the transcript thumbnail
    (`allow-scripts allow-same-origin`) still returns BLOCKED, because the
    effective sandbox is the intersection of the CSP ceiling and the frame's own
    attribute. If either decorative frame gains the token, a generated page could
    take the cursor from a preview the owner never clicked.
    """

    js = RESULTS_JS.read_text(encoding="utf-8")
    offenders = []
    for cls in ("tc-code-artifact-thumb", "tc-code-artifact-shot"):
        for m in re.finditer(re.escape(cls) + r".{0,240}?sandbox=\"([^\"]*)\"", js, re.S):
            if "allow-pointer-lock" in m.group(1):
                offenders.append(f"{cls}: {m.group(1)!r}")

    assert not offenders, (
        "a decorative, non-interactive preview can now capture the mouse "
        "cursor:\n  " + "\n  ".join(offenders)
    )


def test_popups_are_still_refused() -> None:
    """The discipline half: widen only where a deliverable is demonstrably broken.

    No deliverable in the workspace calls `window.open(`, so `allow-popups` has
    no defect behind it. If it ever appears here, it should be because a real
    generated app needed it and was measured failing without it.
    """

    assert "allow-popups" not in _served_sandbox(), (
        "allow-popups was added to the artifact sandbox; no generated deliverable "
        "calls window.open(, so this widens the sandbox with no defect behind it"
    )
