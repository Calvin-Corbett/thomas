"""The "Thomas made this" card must not draw a box around its own controls.

Two different markups share the class `tc-code-artifact`:

    drawer preview     <section class="tc-code-artifact"><header>...   bordered card
    transcript card    <div class="tc-code-artifact">                  three bare pills
                         <div class="tc-code-artifact-row">
                           button.tc-code-artifact-open   (own border)
                           a.tc-code-artifact-pop         (own border)
                           button.tc-code-artifact-save   (own border)

The border rule was written for the first and, unscoped, also framed the second.
That alone would only be redundant. What made it a visible defect is that the
row carries `max-width: 680px` while the turn it sits in is 720px, so the
inherited frame ran 39px past the last control and painted an empty outlined
box beside the download button -- measured at 1920x1080:

    div.tc-code-artifact       x[740..1460]   border 1px solid rgba(255,255,255,.1)
    .tc-code-artifact-row      x[741..1421]   max-width: 680px
                                    ^^^^^^^ 39px of bordered nothing

It reads as a fourth control that failed to draw, which is the same class of
defect as an unmapped icon rendering as a dot: correct in the DOM, wrong on
screen, and invisible to every test that asks whether the buttons exist.

Found by looking at a screenshot, not by a failing assertion.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_results.css"
RESULTS_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_results.js"

# `.tc-code-artifact` exactly -- never `-row`, `-open`, `-pop`, `-save`, `-thumb`.
BARE_CLASS = re.compile(r"\.tc-code-artifact(?![\w-])")


def _blocks(css: str) -> list[tuple[str, str]]:
    """(selector list, declarations) for every rule, comments stripped first.

    Comments go first because this rule is documented directly above itself and
    the documentation quotes the very selector under test -- a scan that reads
    its own comment is how an earlier CSS guard in this suite passed with the
    fix deleted.

    The body pattern is `[^{}]*`, not `[^}]*`. With `[^}]*` an `@media` wrapper
    is consumed as though its brace opened a declaration block, which made a
    different guard fail against a correct fix.
    """

    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", stripped)]


def test_no_unscoped_rule_gives_the_transcript_card_a_border() -> None:
    offenders: list[str] = []
    for selectors, body in _blocks(RESULTS_CSS.read_text(encoding="utf-8")):
        if "border" not in body:
            continue
        for selector in selectors.split(","):
            selector = selector.strip()
            if not BARE_CLASS.search(selector):
                continue
            # A bare `.tc-code-artifact` matches the transcript div too.
            if not selector.startswith("section"):
                offenders.append(f"{selector!r} sets border in {{{body.strip()[:70]}...}}")

    assert not offenders, (
        "a rule borders `.tc-code-artifact` without scoping to the drawer's "
        "`section`, so the transcript card is framed as well -- and its row is "
        "capped 40px narrower than the frame, leaving an empty outlined box "
        "beside the download button:\n  " + "\n  ".join(offenders)
    )


def test_the_drawer_preview_still_gets_its_border() -> None:
    """The opposite failure: scoping so hard that nothing is styled at all.

    Deleting the rule outright would also clear the empty box, and a screenshot
    of the transcript would look identical. The drawer card genuinely wants the
    border, so the scoped selector has to still exist.
    """

    bordered = [
        selectors
        for selectors, body in _blocks(RESULTS_CSS.read_text(encoding="utf-8"))
        if "border:" in body and "section.tc-code-artifact" in selectors
    ]
    assert bordered, (
        "no rule borders `section.tc-code-artifact` any more -- the drawer's "
        "artifact preview has lost the card outline it is supposed to have"
    )


def test_the_two_shapes_still_use_the_elements_the_scoping_assumes() -> None:
    """The fix rests on element names, so pin them.

    `section.tc-code-artifact` protects the transcript card only while that card
    stays a `<div>`. If the renderer ever emits the transcript card as a
    `<section>`, the border comes straight back and both CSS assertions above
    still pass -- they would be checking a distinction the markup no longer
    makes.
    """

    js = RESULTS_JS.read_text(encoding="utf-8")

    assert re.search(r"<div class=\"tc-code-artifact\">\s*\n?\s*<div class=\"tc-code-artifact-row\">", js), (
        "the transcript card is no longer `<div class=\"tc-code-artifact\">` "
        "wrapping `.tc-code-artifact-row`; the `section` scoping that keeps the "
        "border off it may no longer apply"
    )
    assert '<section class="tc-code-artifact"><header>' in js, (
        "the drawer preview is no longer a `<section>` with a header, so the "
        "`section.tc-code-artifact` border rule now styles nothing"
    )
