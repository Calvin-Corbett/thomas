"""The layout must reserve room for the Activity drawer, not let it overlap.

The drawer is a side panel, and the layout reserved nothing for it. Measured in
the live UI with the drawer open -- transcript right edge against drawer left
edge::

    1920 -> -176px  clear, and only by luck: the turn is 720px and centred
    1440 -> +64px   of content underneath
    1100 -> +234px  of content underneath

`padding-right` computed as 0px at every one of those widths. At 1100 the run
summary was cut mid-sentence -- "so this task is unfinish" -- the deliverable
card was clipped through its middle, and the verdict card ran under the panel.

The file viewer beside it already had this treatment
(`.tc-code-panel.is-viewer-open .tc-code-layout`), which is what made the
omission visible: two panels on the same edge, one making room and one not.

Pinned to the behaviour -- the reservation is driven by the SAME custom property
as the drawer's own width -- rather than to a pixel value, because a resized
drawer must keep its clearance. A hard-coded 360px here would silently go wrong
the moment someone dragged the handle.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_activity.css"
MODE_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_mode.css"

DRAWER_WIDTH_VAR = "--tc-code-drawer-width"
DRAWER_RULE = r"\.tc-code-panel\.is-drawer-open\s+\.tc-code-layout"


def _strip_comments(css: str) -> str:
    """Comments go first.

    Everything between `}` and `{` reads as a selector, so a comment mentioning
    one satisfies a naive match -- two earlier versions of a sibling test passed
    with their fix deleted for exactly that reason, and the comment above this
    rule discusses the selector at length.
    """

    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _body_for(css: str, selector_pattern: str) -> str:
    """The declaration block belonging to a selector, wherever it is nested.

    Deliberately NOT a generic `selector { body }` splitter: the rule under test
    lives inside an `@media` block, and a `([^{}]+)\\{([^}]*)\\}` scan treats the
    at-rule's own brace as the opener -- so the selector it reports is
    `@media (min-width: 721px)` and the real one lands in the body. That is how
    the first version of this file failed against a fix that was already correct.
    """

    match = re.search(selector_pattern + r"\s*\{([^}]*)\}", _strip_comments(css))
    return match.group(1) if match else ""


def test_the_layout_reserves_room_when_the_drawer_is_open() -> None:
    body = _body_for(ACTIVITY_CSS.read_text(encoding="utf-8"), DRAWER_RULE)

    assert body, "nothing reserves space for the open drawer, so it sits on the transcript"
    assert "padding-right" in body, "the reservation must be horizontal room on the drawer's side"


def test_the_reservation_follows_the_drawer_width() -> None:
    """A fixed pixel value goes wrong the moment the drawer is resized."""

    body = _body_for(ACTIVITY_CSS.read_text(encoding="utf-8"), DRAWER_RULE)
    assert DRAWER_WIDTH_VAR in body, (
        f"the reservation must come from {DRAWER_WIDTH_VAR}, the same property the "
        "drawer's own width uses, or the two drift apart when it is dragged"
    )

    # And that property really is what sizes the drawer, so this stays coupled.
    drawer = _body_for(MODE_CSS.read_text(encoding="utf-8"), r"\.tc-code-actions")
    assert DRAWER_WIDTH_VAR in drawer, (
        f"{DRAWER_WIDTH_VAR} no longer sizes the drawer; point the reservation at "
        "whatever replaced it rather than leaving it measuring nothing"
    )


def test_the_narrow_overlay_breakpoint_is_left_alone() -> None:
    """Below 720px the drawer is a near-full-width overlay on purpose.

    Reserving `min(420px, 94vw)` there would leave the transcript no room at all,
    so the reservation must be gated above that breakpoint.
    """

    css = re.sub(r"/\*.*?\*/", "", ACTIVITY_CSS.read_text(encoding="utf-8"), flags=re.S)
    index = css.find("is-drawer-open")
    assert index != -1, "expected the drawer reservation rule"
    preceding = css[:index]
    assert "min-width" in preceding.split("@media")[-1], (
        "the reservation must sit inside a min-width media query so the narrow "
        "full-width overlay keeps its behaviour"
    )
