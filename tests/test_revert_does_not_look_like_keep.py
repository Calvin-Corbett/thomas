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
# Since the 2026-10 Build redesign the drawer's OUTPUTS rows (Keep / Revert) are
# drawn by unified_code_drawer.js and styled with the agents.
AGENTS_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_agents.css"
ACTIVITY_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_activity.css"
TOKENS_CSS = ROOT / "thomas" / "server" / "web" / "css" / "tokens.css"

FAILURE_COLOUR = "#ff9a9a"
REVERT = "button.tc-agents-revert"


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
    css = AGENTS_CSS.read_text(encoding="utf-8")
    resting = _rule_body(css, REVERT, resting_only=True)

    assert resting, "Revert has no resting style of its own, so it renders identically to Keep"
    assert _COLOR_DECLARATION.search(resting), (
        "Revert must take a text colour that distinguishes it from Keep at rest, not only on hover"
    )


def test_revert_uses_the_colour_failure_already_uses() -> None:
    """A second, unrelated red would be a new system rather than the same one.

    The drawer rides the Build palette's token (`--c-danger`), which tokens.css
    pins to the failed-verdict rail's colour in Build."""

    revert = _rule_body(AGENTS_CSS.read_text(encoding="utf-8"), REVERT, resting_only=True)
    assert "var(--c-danger)" in revert, "Revert should take the failure colour's token"
    tokens = TOKENS_CSS.read_text(encoding="utf-8")
    # The one Dark every page wears unless Light is chosen; it was Build's own block before 2026-11-10.
    build = tokens[tokens.index(':where(html:not([data-theme="light"])') :]
    assert f"--c-danger: {FAILURE_COLOUR}" in build[: build.index("}")].lower(), (
        f"Build's --c-danger is no longer {FAILURE_COLOUR}, the failed-verdict rail's colour"
    )

    activity = ACTIVITY_CSS.read_text(encoding="utf-8").lower()
    assert FAILURE_COLOUR in activity, (
        f"{FAILURE_COLOUR} is no longer the failure colour; pick up whatever replaced it "
        "rather than leaving Revert on an orphaned red"
    )


def test_keep_is_left_alone() -> None:
    """The point is the contrast. Styling both would restore the problem."""

    keep = _rule_body(AGENTS_CSS.read_text(encoding="utf-8"), "button.tc-agents-keep")
    assert keep, "Keep has no rule at all"
    assert "--c-danger" not in keep and FAILURE_COLOUR not in keep.lower(), (
        "Keep must not borrow the destructive colour"
    )


def test_the_revert_rule_can_still_win_over_the_shared_rule() -> None:
    """Order is load-bearing: the rule Keep and Revert share sets a neutral
    colour, and at equal specificity the later rule wins. If the shared rule is
    ever moved below Revert's own, Revert silently looks like Keep again."""

    css = re.sub(r"/\*.*?\*/", "", AGENTS_CSS.read_text(encoding="utf-8"), flags=re.S)
    shared = css.find("button.tc-agents-keep,")
    revert_rule = css.find(".tc-agents-drawer button.tc-agents-revert {")
    assert shared != -1 and revert_rule != -1, "expected both rules to exist"
    assert revert_rule > shared, (
        "the Revert rule must stay after the rule it shares with Keep; at equal "
        "specificity the later rule wins, and moving it up makes Revert look like Keep again"
    )
