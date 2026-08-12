"""The Activity drawer must never sit on top of the Code transcript.

That is the property, and it has not changed. What changed is the machinery
underneath it, so this module was rewritten on 2026-08-10 to guard the
mechanism that is actually shipping instead of the one it replaced.

The original fault: the drawer is an absolutely positioned side panel and the
layout reserved nothing for it. Measured in the live UI with the drawer open --
transcript right edge against drawer left edge::

    1920 -> -176px  clear, and only by luck: the turn is 720px and centred
    1440 -> +64px   of content underneath
    1100 -> +234px  of content underneath

At 1100 the run summary was cut mid-sentence -- "so this task is unfinish" --
the deliverable card was clipped through its middle, and the verdict card ran
under the panel.

The first fix borrowed the file viewer's treatment: `padding-right` on
`.tc-code-panel.is-drawer-open .tc-code-layout`. It cleared the overlap and
introduced a worse fault, because shrinking the layout re-centres a centred
column, and re-centring IS a slide. Measured at 1920 the instant the Activity
button was pressed::

    chat column   716..1484  ->  576..1344   (slid 140px left)
    composer      734..1502  ->  734..1502   (did not move at all)

Commit `c82622aa` deleted that rule on the owner's explicit instruction, quoted
in `unified_code_activity.css`: "pressing the activity button should [not] slide
the chat -- that menu isn't wide enough to need that, it can just open and the
chat stays where it is." Symmetric padding was tried next and is also wrong: it
holds the centre still but pays the reserve twice, and at 900px it left a 12px
column.

So the drawer no longer touches the LAYOUT at all. The clearance is now a cap on
the reading column's own width, and the chain runs:

    unified_code_results.js  publishColumnState() writes `data-code-side` and
                             `--tc-code-drawer-width` onto `#tc-shell`
    unified_code_mode.css    `--tc-code-col-reserve` on the activity state,
                             derived from that same drawer width
    unified_code_mode.css    `--tc-code-col-width` subtracts the reserve while
                             `--tc-code-col-inset` deliberately ignores it
    consumed by              `.tc-code-transcript > *` and the composer's
                             `.tc-rail`, which sit in different subtrees

The column therefore keeps its left edge and simply stops short of the drawer.
Measured after, left edge open vs closed::

    1920  716 / 716   (768px wide either way -- nothing moves at all)
    1440  476 / 476   (768 -> 660, stops 24px short of the drawer)
    1100  306 / 306   (768 -> 490)
     900  304 / 304   (572 -> 292)

Pinned to the behaviour rather than to any pixel value, for the reason the
earlier version of this module already understood: the reserve and the drawer's
own width must come from ONE property, or a dragged handle moves the panel
without moving the clearance. The tests below keep that coupling, keep the
narrow-overlay breakpoint exempt, and additionally require that the reserve is
actually spent -- a custom property nothing reads is not a protection.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_activity.css"
MODE_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_mode.css"

# The channel `publishColumnState()` writes onto the shell, and the three
# properties every box in Code is built from.
ACTIVITY_STATE = 'data-code-side="activity"'
DRAWER_WIDTH_VAR = "--tc-code-drawer-width"
RESERVE_VAR = "--tc-code-col-reserve"
WIDTH_VAR = "--tc-code-col-width"
INSET_VAR = "--tc-code-col-inset"


def _strip_comments(css: str) -> str:
    """Comments go first.

    Everything between `}` and `{` reads as a selector, so a comment mentioning
    one satisfies a naive match -- two earlier versions of a sibling test passed
    with their fix deleted for exactly that reason, and the comments around
    these rules discuss the selectors, the deleted padding rule and the owner's
    instruction at length.
    """

    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rules(path: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    """Every declaration block in a stylesheet, with the at-rules wrapping it.

    Deliberately a brace scanner rather than a `selector { body }` regex: the
    rule under test lives inside an `@media` block, and a `([^{}]+)\\{([^}]*)\\}`
    scan treats the at-rule's own brace as the opener -- so the selector it
    reports is `@media (min-width: 721px)` and the real one lands in the body.
    That is how an earlier version of this file failed against a fix that was
    already correct. Reporting the enclosing at-rules explicitly also means the
    breakpoint test below can read the gate instead of guessing at it from the
    surrounding text.
    """

    text = _strip_comments(path.read_text(encoding="utf-8"))
    rules: list[tuple[str, str, tuple[str, ...]]] = []
    open_blocks: list[tuple[str, int]] = []
    cursor = 0
    for token in re.finditer(r"[{}]", text):
        preamble = text[cursor : token.start()].strip()
        cursor = token.end()
        if token.group() == "{":
            open_blocks.append((preamble, token.end()))
            continue
        if not open_blocks:
            continue
        selector, body_start = open_blocks.pop()
        body = text[body_start : token.start()]
        if "{" not in body:  # a nested block is an at-rule, not a rule of its own
            rules.append((selector, body, tuple(block[0] for block in open_blocks)))
    return rules


def _declaration(body: str, prop: str) -> str:
    """The value of one declaration, anchored so `width` cannot match `min-width`."""

    match = re.search(r"(?:^|[;{])\s*" + re.escape(prop) + r"\s*:\s*([^;]+);", body, flags=re.M)
    return match.group(1).strip() if match else ""


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _rule_declaring(path: Path, matches, prop: str) -> tuple[str, tuple[str, ...]]:
    """The value of `prop` in the first rule whose selector satisfies `matches`."""

    for selector, body, enclosing in _rules(path):
        if matches(selector):
            value = _declaration(body, prop)
            if value:
                return value, enclosing
    return "", ()


def test_the_reserve_is_driven_by_the_drawers_own_width() -> None:
    """One property sizes the drawer and buys the clearance, or they drift.

    The handle is draggable (280..520px, persisted to localStorage), so a
    hard-coded 360px here would be silently wrong the moment someone resized the
    panel: the drawer would move and the clearance would not.
    """

    reserve, _ = _rule_declaring(MODE_CSS, lambda sel: ACTIVITY_STATE in sel, RESERVE_VAR)
    assert reserve, (
        f"no rule sets {RESERVE_VAR} for the open-drawer state ([{ACTIVITY_STATE}] on the "
        "shell), so nothing keeps the drawer off the transcript"
    )
    assert DRAWER_WIDTH_VAR in reserve, (
        f"the reserve must come from {DRAWER_WIDTH_VAR}, the same property the drawer's own "
        f"width uses, or the two drift apart when the handle is dragged: {reserve!r}"
    )

    # And that property really is what sizes the drawer, so this stays coupled.
    drawer, _ = _rule_declaring(MODE_CSS, lambda sel: _squash(sel) == ".tc-code-actions", "width")
    assert DRAWER_WIDTH_VAR in drawer, (
        f"{DRAWER_WIDTH_VAR} no longer sizes the drawer; point the reserve at whatever "
        f"replaced it rather than leaving it measuring nothing: {drawer!r}"
    )
    assert _squash(drawer) in _squash(reserve), (
        "the drawer's width and the reserve no longer clamp identically, so at some viewport "
        f"the reserve buys less room than the drawer takes: drawer {drawer!r} vs reserve {reserve!r}"
    )


def test_the_narrow_overlay_breakpoint_is_left_alone() -> None:
    """Below 720px the drawer is a near-full-width overlay on purpose.

    It becomes `min(420px, 94vw)` with its resize handle hidden. Reserving that
    much there would leave the transcript no column at all, so the reserve must
    stay gated above the breakpoint -- not merely inside some media query.
    """

    reserve, enclosing = _rule_declaring(MODE_CSS, lambda sel: ACTIVITY_STATE in sel, RESERVE_VAR)
    assert reserve, "expected the drawer reserve rule"
    assert enclosing, (
        "the reserve is not gated by any media query, so the narrow full-width overlay would "
        "reserve nearly the whole viewport and leave no transcript"
    )
    gate = enclosing[-1]
    assert "min-width" in gate and "max-width" not in gate, (
        f"the reserve must sit inside a min-width media query so the narrow full-width overlay "
        f"keeps its behaviour, not {gate!r}"
    )


def test_the_reserve_narrows_the_column_without_moving_it() -> None:
    """The reserve has to be spent, and spent on width alone.

    Two halves, and both matter. If `--tc-code-col-width` stops subtracting it,
    or nothing reads the result, the property is a number no box obeys and the
    drawer is back on top of the transcript. If `--tc-code-col-inset` starts
    subtracting it, the column's left edge moves again -- which is the slide the
    owner rejected, arriving by a new route.

    The transcript and the composer are in different subtrees and must read the
    same property: the owner's other instruction was "when side panels move and
    stuff the composer should shrink exactly the same size as the chat".
    """

    def is_code_shell(selector: str) -> bool:
        return _squash(selector) == '#tc-shell[data-surface-mode="code"]'

    width, _ = _rule_declaring(MODE_CSS, is_code_shell, WIDTH_VAR)
    assert f"var({RESERVE_VAR}" in _squash(width), (
        f"{WIDTH_VAR} no longer subtracts {RESERVE_VAR}, so the reserve buys nothing and the "
        f"column runs under the drawer: {width!r}"
    )

    inset, _ = _rule_declaring(MODE_CSS, is_code_shell, INSET_VAR)
    assert inset, f"{INSET_VAR} is gone; the column has no anchored left edge"
    assert RESERVE_VAR not in inset, (
        f"{INSET_VAR} must not depend on what is open, or opening the drawer slides the "
        f"conversation out from under the composer again: {inset!r}"
    )

    transcript, _ = _rule_declaring(
        ACTIVITY_CSS, lambda sel: _squash(sel) == ".tc-code-transcript>*", "width"
    )
    assert f"var({WIDTH_VAR}" in _squash(transcript), (
        f"the transcript's turns no longer take their width from {WIDTH_VAR}, so the cap that "
        f"keeps them off the drawer reaches nothing: {transcript!r}"
    )

    rail, _ = _rule_declaring(
        MODE_CSS, lambda sel: ".tc-rail" in sel and "chat.composer" in sel, "width"
    )
    assert f"var({WIDTH_VAR}" in _squash(rail), (
        f"the composer's rail no longer takes its width from {WIDTH_VAR}, so it stops matching "
        f"the conversation directly above it: {rail!r}"
    )
