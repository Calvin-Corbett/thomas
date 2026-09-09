"""An Export button in a generated app has to actually produce a file.

Thomas was asked for a to-do list with an "Export CSV" button and built a
correct one. Driven through Thomas's own artifact route the button did nothing
at all -- no file, no error, no console message. The identical bytes, served
from a plain local http server with no sandbox, downloaded
``tasks-2026-07-30.csv`` immediately.

    through Thomas                NO DOWNLOAD (timeout)
    same HTML, plain http server  tasks-2026-07-30.csv

Same browser, same clicks, same page: only the sandbox differed. That control is
what makes this Thomas's defect rather than the model writing a broken export --
without it, a timeout is equally consistent with a bad page.

Fourth instance of one shape, and the only one caught on output built AFTER the
earlier fixes shipped:

    'unsafe-eval' missing      a correct calculator printed "Error"
    allow-modals missing       every confirm-before-delete button was dead
    allow-pointer-lock missing an FPS could shoot but not turn
    allow-downloads missing    every export/save/report button produced nothing

Census across 442 generated files under ~/.thomas: modals 9, pointer lock 3,
downloads 3, popups 0. `allow-popups` stays ungranted for exactly that reason.

Verified both ways after the fix. Removing the token: Thomas NONE, control OK.
Restoring it: both OK.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELIVERABLE = ROOT / "thomas" / "server" / "routes" / "deliverable_aiohttp.py"
RESULTS_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_results.js"


def _served_sandbox() -> str:
    """The artifact preview's CSP sandbox directive.

    Two normalisations, each of which has already produced a wrong answer in
    this suite:

    * comments are stripped, because the directive is documented directly above
      itself and the documentation quotes it -- a scan that reads its own
      comment passes with the change deleted;
    * adjacent string literals are joined, because the directive outgrew one
      line and Python implicitly concatenates them. Anchoring on the opening
      quote stopped at the first closing quote and reported `allow-pointer-lock`
      missing while it was plainly present on the next line.
    """

    text = DELIVERABLE.read_text(encoding="utf-8")
    without_comments = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    joined = re.sub(r'"\s*\n\s*"', "", without_comments)
    directives = [m.group(1) for m in re.finditer(r'"sandbox ([^";]*)', joined)]
    served = [d for d in directives if "allow-same-origin" in d]
    assert served, "no artifact sandbox directive grants allow-same-origin any more"
    return served[0]


def test_the_artifact_csp_permits_downloads() -> None:
    directive = _served_sandbox()
    assert "allow-downloads" in directive, (
        "the artifact CSP sandbox omits allow-downloads, so every generated "
        "Export/Save/Download button silently produces nothing -- no file, no "
        f"error. Got: {directive!r}"
    )


def test_the_viewer_stage_opts_in_to_downloads() -> None:
    """The CSP is a ceiling; the surface the owner clicks has to opt in too."""

    js = RESULTS_JS.read_text(encoding="utf-8")
    stage = re.search(r"tc-code-viewer-stage.{0,240}?sandbox=\"([^\"]*)\"", js, re.S)
    assert stage, "the viewer stage iframe is gone or no longer carries a sandbox attribute"
    assert "allow-downloads" in stage.group(1), (
        "the viewer stage -- where the owner uses the app -- does not allow "
        f"downloads, so Export there still produces nothing. Got: {stage.group(1)!r}"
    )


def test_the_decorative_previews_cannot_start_downloads() -> None:
    """A preview the owner never clicked must not be able to write to disk.

    The effective sandbox is the intersection of the CSP ceiling and the frame's
    own attribute, so raising the ceiling must not let a 168px thumbnail begin a
    download on load.
    """

    js = RESULTS_JS.read_text(encoding="utf-8")
    offenders = []
    for cls in ("tc-code-artifact-thumb", "tc-code-artifact-shot"):
        for m in re.finditer(re.escape(cls) + r".{0,240}?sandbox=\"([^\"]*)\"", js, re.S):
            if "allow-downloads" in m.group(1):
                offenders.append(f"{cls}: {m.group(1)!r}")

    assert not offenders, (
        "a decorative, non-interactive preview can now start a download:\n  "
        + "\n  ".join(offenders)
    )
