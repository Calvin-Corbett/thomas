"""Opening the viewer must not reduce the conversation to a sliver.

The viewer and the space reserved for it were two copies of
`min(760px, 62vw)`. `62vw` was the bug: the viewer sits inside the panel, but
`vw` measures the VIEWPORT, and the panel is the viewport minus a 280px sidebar
-- so the viewer's share of the space it actually occupies grows as the window
narrows.

Measured with a file open, transcript width::

    1920 -> 720px
    1440 -> 352px
    1100 ->  90px

At 1100 the conversation was a ninety-pixel column setting one word per line:
"hides / the / others, / and / marks / itself". Nothing numeric flagged it -- the
document did not overflow at any width -- it only shows in the picture.

Kept separate from the Activity drawer's guard because the failure is the mirror
image: the drawer covered the transcript, this squeezed it. Both are "a panel on
the right edge took space the reading column needed".
"""

from __future__ import annotations

import re
from pathlib import Path

ACTIVITY_CSS = (
    Path(__file__).resolve().parents[1]
    / "thomas" / "server" / "web" / "css" / "unified_code_activity.css"
)

VIEWER_WIDTH_VAR = "--tc-code-viewer-width"

# The declaration moved up one element on 2026-08-10 (c82622aa): the composer is
# the shell's, not the panel's, so both readers now inherit the width from
# `#tc-shell[data-surface-mode="code"]` instead of `.tc-code-panel`. Same file,
# same value, one element higher -- but a pattern pinned to the panel matched
# nothing and returned "", and an empty string satisfies none of the checks
# below by reading them, only by never reaching them. Either owner is accepted
# so the guard survives the value moving back.
WIDTH_OWNER = r"(?:\.tc-code-panel\b(?![.\w-])|#tc-shell\[data-surface-mode=\"code\"\](?!\s*[\[.\w]))"


def _css() -> str:
    """Comments stripped first -- the comment above the rule quotes the selector
    and the old expression at length, and a naive scan matches its own docs."""

    return re.sub(r"/\*.*?\*/", "", ACTIVITY_CSS.read_text(encoding="utf-8"), flags=re.S)


def _declaration(selector_pattern: str, prop: str) -> str:
    """One property's value from the rule matching a selector, nesting-safe.

    Matches the selector directly rather than splitting on braces: a
    `([^{}]+)\\{([^}]*)\\}` scan treats an `@media` brace as the opener and
    reports the at-rule as the selector, which already made a sibling guard fail
    against a fix that was correct.
    """

    block = re.search(selector_pattern + r"\s*\{([^}]*)\}", _css())
    if not block:
        return ""
    found = re.search(rf"(?:^|[;{{])\s*{prop}\s*:\s*([^;]+)", block.group(1))
    return found.group(1).strip() if found else ""


def test_the_viewer_and_its_reservation_are_one_value() -> None:
    """Two copies of the same width have to agree; one value cannot disagree."""

    width = _declaration(r"\.tc-code-viewer", "width")
    reserved = _declaration(r"\.tc-code-panel\.is-viewer-open\s+\.tc-code-layout", "padding-right")

    assert width, "the viewer has no width rule"
    assert reserved, "nothing reserves space for the open viewer"
    assert VIEWER_WIDTH_VAR in width, f"the viewer's width must come from {VIEWER_WIDTH_VAR}"
    assert VIEWER_WIDTH_VAR in reserved, f"the reservation must come from {VIEWER_WIDTH_VAR}"


def test_the_width_accounts_for_the_sidebar_and_leaves_a_reading_column() -> None:
    """A bare `vw` fraction is what collapsed the transcript to 90px.

    The value has to subtract the chrome the viewer does not own -- the sidebar,
    plus a floor for the conversation -- rather than taking a share of the whole
    window.
    """

    value = _declaration(WIDTH_OWNER, VIEWER_WIDTH_VAR)
    assert value, f"{VIEWER_WIDTH_VAR} is not defined on the panel"

    assert "calc(" in value and "100vw" in value, (
        "the width must be derived by subtracting from the viewport, not taken as "
        f"a fraction of it; got {value!r}"
    )
    assert not re.search(r"\b\d+vw\b", value.replace("100vw", "")), (
        f"a bare vw fraction is the bug this replaced; got {value!r}"
    )
    assert "max(" in value, (
        "the viewer needs a floor too, or it shrinks to a strip at narrow widths "
        "-- the same mistake in the other direction"
    )
