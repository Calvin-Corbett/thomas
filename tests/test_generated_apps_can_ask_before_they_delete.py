"""A generated app's confirm-before-delete has to actually ask.

Thomas built a habit tracker whose Reset button reads:

    document.getElementById("reset").addEventListener("click", () => {
      if (!confirm("Clear all habit checkoffs?")) return;
      localStorage.removeItem(storageKey);

Clicking it did nothing at all: no dialog, no error, no console message. The
artifact CSP carried `sandbox allow-scripts allow-forms allow-same-origin` with
no `allow-modals`, which makes `confirm()` return false and show nothing, so the
guard clause took the early exit every time.

Measured on the live page, and the control is what makes it evidence:

    real click                    2 checked -> 2   (no dialog fired)
    window.confirm forced true    2 checked -> 0   (cleared)

The page's logic was correct throughout. This is the same shape as the missing
`'unsafe-eval'` that made a correct calculator print `Error` -- the sandbox
silently removing a capability ordinary pages rely on, with no diagnostic.

Because it is a CSP `sandbox` directive it also applied to the TOP-LEVEL
document, so "open in a new tab" produced the same dead button.

The grant is deliberately asymmetric, and that asymmetry is the point of this
file. The effective sandbox is the INTERSECTION of the CSP ceiling and each
iframe's own `sandbox` attribute, so raising the ceiling must not let a 168px
decorative thumbnail pop a dialog over the chat. Verified live after the change:

    top level                                   dialog fires, clears
    viewer stage (allow-modals)                 dialog fires, clears
    transcript thumbnail (no allow-modals)      confirm() -> false, no dialog
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELIVERABLE = ROOT / "thomas" / "server" / "routes" / "deliverable_aiohttp.py"
RESULTS_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_results.js"


def _sandbox_directives(text: str) -> list[str]:
    """Every `sandbox ...` CSP directive, comments stripped first.

    Comments first because the change is documented directly above itself and
    the documentation quotes the directive -- a scan that reads its own comment
    is how an earlier CSS guard in this suite passed with the fix deleted.
    """

    without_comments = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    # Join adjacent string literals first: the directive outgrew one line and
    # Python implicitly concatenates them, so a scan anchored on the opening
    # quote stops at the first closing quote and reports tokens missing that are
    # plainly there.
    joined = re.sub(r'"\s*\n\s*"', "", without_comments)
    return [m.group(1) for m in re.finditer(r'"sandbox ([^";]*)', joined)]


def test_the_artifact_csp_permits_modals() -> None:
    directives = _sandbox_directives(DELIVERABLE.read_text(encoding="utf-8"))
    assert directives, "no CSP sandbox directive found; this guard is checking nothing"

    served = [d for d in directives if "allow-same-origin" in d]
    assert served, "no artifact sandbox directive grants allow-same-origin any more"
    for directive in served:
        assert "allow-modals" in directive, (
            "the artifact CSP sandbox omits allow-modals, so confirm(), alert() "
            "and prompt() return false and show nothing. Every generated app "
            "with a confirm-before-delete has a silently dead button, in the "
            f"preview and in a new tab alike. Got: {directive!r}"
        )


def test_the_viewer_stage_opts_in() -> None:
    """The CSP is only a ceiling; the surface has to opt in as well."""

    js = RESULTS_JS.read_text(encoding="utf-8")
    stage = re.search(r"tc-code-viewer-stage.{0,200}?sandbox=\"([^\"]*)\"", js, re.S)
    assert stage, "the viewer stage iframe is gone or no longer carries a sandbox attribute"
    assert "allow-modals" in stage.group(1), (
        "the viewer stage -- the surface the owner actually uses the app on -- "
        f"does not allow modals, so confirm() there still silently returns false. Got: {stage.group(1)!r}"
    )


def test_the_decorative_previews_still_refuse_modals() -> None:
    """The other half of the fix: a picture must not be able to interrupt you.

    The transcript thumbnail and the drawer shot are `tabindex="-1"` decoration.
    If either gains allow-modals, a generated page that calls confirm() during
    init can throw a dialog over the chat from a 168px image the owner never
    clicked.
    """

    js = RESULTS_JS.read_text(encoding="utf-8")
    offenders = []
    for cls in ("tc-code-artifact-thumb", "tc-code-artifact-shot"):
        for m in re.finditer(re.escape(cls) + r".{0,240}?sandbox=\"([^\"]*)\"", js, re.S):
            if "allow-modals" in m.group(1):
                offenders.append(f"{cls}: {m.group(1)!r}")

    assert not offenders, (
        "a decorative, non-interactive preview now allows modals; a generated "
        "page could pop a dialog over the chat without the owner clicking "
        "anything:\n  " + "\n  ".join(offenders)
    )
