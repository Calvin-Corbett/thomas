"""A long filename must not run out of the Activity drawer.

The drawer is about 280px and shows names in four places. Two truncated with an
ellipsis and two did not -- the same "every sibling but one" shape as
`overflow-wrap` on the user bubble and `--c-danger` on the light themes.

Measured with an 86-character unbreakable name, scrollWidth vs clientWidth::

    change row name   491 / 137   ellipsis      fine
    artifact name     607 / 386   ellipsis      fine
    tree file row     518 / 247   text-overflow: CLIP, spilling past the panel
    drawer subtitle   458 / 458   grew to 458px inside a 280px drawer

The subtitle also pushed the drawer's × close button off the panel, so a long
project name made the drawer impossible to close. That is functional, not
cosmetic.

Two separate causes, and the first fix only addressed one of them:

* `text-overflow` needs a block container. The tree row is `display: flex` and
  the name was a bare text node, which becomes an anonymous flex item the
  property never reaches -- so the name is wrapped in a span the CSS can target.
* A flex ITEM defaults to `min-width: auto` and refuses to shrink below its
  content. Setting ellipsis on the `small` alone left the wrapper growing to fit
  the label; it still measured 458px wide with the ellipsis applied. Both levels
  are needed, which is why the wrapper rule is asserted here too.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODE_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_mode.css"
CODE_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_mode.js"


def _rule(selector_pattern: str) -> str:
    """Every declaration block for a selector, comments stripped first.

    Comments first because the rules under test are documented directly above
    themselves and quote their own selectors -- a scan that reads its own
    documentation is how three earlier CSS guards in this suite passed against
    deleted fixes.

    EVERY matching block, joined -- not the first. A selector legitimately
    appears in more than one rule: `.tc-code-drawer-head small` is in a shared
    `display: block` rule as well as its own. Taking the first match read the
    wrong one and failed against a fix that was already correct. The browser
    applies both, so this has to look at both.
    """

    css = re.sub(r"/\*.*?\*/", "", MODE_CSS.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        m.group(1) for m in re.finditer(selector_pattern + r"[^{}]*\{([^}]*)\}", css)
    )


def _truncates(body: str) -> bool:
    return (
        "overflow: hidden" in body
        and "text-overflow: ellipsis" in body
        and "white-space: nowrap" in body
    )


def test_the_file_tree_truncates_a_long_name() -> None:
    body = _rule(r"\.tc-code-tree li > button > span")
    assert body, "the tree filename has no rule of its own, so it clips mid-character"
    assert _truncates(body), f"the tree filename must truncate with an ellipsis; got {body.strip()!r}"


def test_the_tree_markup_actually_emits_that_span() -> None:
    """CSS aimed at an element nobody renders is a silent no-op.

    The rule above targets `button > span`. If the renderer goes back to putting
    the filename in as a bare text node, the CSS matches nothing and the guard
    above still passes -- so the markup is pinned separately.
    """

    js = CODE_JS.read_text(encoding="utf-8")
    assert re.search(r"data-code-tree-file=.{0,120}<span>", js, re.S), (
        "the tree row no longer wraps its filename in a span, so the truncation "
        "rule matches nothing"
    )


def test_the_drawer_subtitle_truncates_and_its_wrapper_can_shrink() -> None:
    subtitle = _rule(r"\.tc-code-drawer-head small")
    assert _truncates(subtitle), (
        f"the drawer subtitle must truncate; got {subtitle.strip()!r}"
    )

    wrapper = _rule(r"\.tc-code-drawer-head > div")
    assert "min-width: 0" in wrapper, (
        "the subtitle's flex wrapper defaults to min-width:auto and will not "
        "shrink, so the ellipsis never engages and the label still runs out of "
        "the drawer -- measured at 458px inside a 280px panel"
    )
