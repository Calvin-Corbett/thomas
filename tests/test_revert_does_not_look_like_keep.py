"""A destructive control must not be drawn like a harmless one beside it.

The Activity drawer lists every changed file with two buttons: `Keep`, which is
benign, and `Revert`, which permanently discards that file's changes -- its own
approval card says "This permanently discards its current changes", and for a
new file it deletes the file outright.

Measured in the live drawer on a real run, the two were identical on **every**
visual property: colour `rgb(238,240,251)`, background `rgba(0,0,0,0)`, border
`1px solid rgba(255,255,255,0.1)`, font-weight 400, font-size 9.5px, padding
`3px 6px`. The only difference between them was the 6px of width the longer word
adds. A three-file run therefore renders six buttons that look the same and mean
opposite things.

`#ff9a9a` is not a new colour: it is what the failed-verdict rail and icon in
`unified_code_activity.css` already use, so the drawer reads as one system.

Pinned to the behaviour -- Revert is given a colour of its own, and that colour
is the one failure already uses -- rather than to a spelling of the rule, because
a test that names one exact declaration is how `test_marketplace_uses_native_
runtime_shell` sat red for nine days.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODE_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_mode.css"
ACTIVITY_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_activity.css"

FAILURE_COLOUR = "#ff9a9a"


# `\bcolor\s*:` also matches `border-color:` -- `-` is a word boundary, so the
# first version of this file passed with the rule deleted. A property only starts
# at the beginning of a declaration, so anchor on the separator instead.
_COLOR_DECLARATION = re.compile(r"(?:^|[;{])\s*color\s*:", re.M)


def _rule_body(css: str, selector_fragment: str, *, resting_only: bool = False) -> str:
    """Every declaration block whose selector mentions the fragment.

    ``resting_only`` drops `:hover` and friends. It matters: deleting the resting
    rule and leaving the hover one makes Revert look exactly like Keep until the
    pointer is already on it, and a check that accepts either rule cannot see
    that -- which is how the first version of this test passed with the fix
    removed.
    """

    # Comments MUST go first. Everything between `}` and `{` reads as the
    # selector, so a comment that merely mentions the selector satisfies the
    # match -- and the comment above this very rule quotes it while explaining
    # the specificity. Two earlier versions of this test passed with the fix
    # deleted for exactly that reason.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found = []
    for match in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        selector = match.group(1)
        if selector_fragment not in selector:
            continue
        if resting_only and ":" in selector.split(selector_fragment, 1)[1]:
            continue
        found.append(match.group(2))
    return "\n".join(found)


def test_revert_is_not_drawn_like_keep() -> None:
    css = MODE_CSS.read_text(encoding="utf-8")
    resting = _rule_body(css, "data-code-revert", resting_only=True)

    assert resting, "Revert has no resting style of its own, so it renders identically to Keep"
    assert _COLOR_DECLARATION.search(resting), (
        "Revert must take a text colour that distinguishes it from Keep at rest, "
        "not only on hover"
    )


def test_revert_uses_the_colour_failure_already_uses() -> None:
    """A second, unrelated red would be a new system rather than the same one."""

    revert = _rule_body(MODE_CSS.read_text(encoding="utf-8"), "data-code-revert", resting_only=True)
    assert FAILURE_COLOUR in revert.lower(), (
        f"Revert should reuse {FAILURE_COLOUR}, the colour the failed-verdict rail already uses"
    )

    activity = ACTIVITY_CSS.read_text(encoding="utf-8").lower()
    assert FAILURE_COLOUR in activity, (
        f"{FAILURE_COLOUR} is no longer the failure colour; pick up whatever replaced it "
        "rather than leaving Revert on an orphaned red"
    )


def test_keep_is_left_alone() -> None:
    """The point is the contrast. Styling both would restore the problem."""

    css = MODE_CSS.read_text(encoding="utf-8")
    keep = _rule_body(css, "data-code-keep")
    assert FAILURE_COLOUR not in keep.lower(), "Keep must not borrow the destructive colour"


def test_the_revert_rule_can_still_win_over_the_shared_hover() -> None:
    """Equal specificity means source order decides, so order is load-bearing.

    `.tc-code-change button:hover` and `.tc-code-change button[data-code-revert]`
    both score (0,2,1). If the shared rule is ever moved below this one, Revert
    silently loses its colour on hover and the two look alike again at exactly
    the moment someone is about to click.
    """

    css = MODE_CSS.read_text(encoding="utf-8")
    shared_hover = css.find(".tc-code-change button:hover")
    revert_rule = css.find(".tc-code-change button[data-code-revert]")
    assert shared_hover != -1 and revert_rule != -1, "expected both rules to exist"
    assert revert_rule > shared_hover, (
        "the Revert rule must stay after the shared hover rule; at equal specificity "
        "the later rule wins, and moving it up makes Revert look like Keep again"
    )
