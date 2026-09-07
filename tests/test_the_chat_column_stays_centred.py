"""The reading column sits in the middle of the space it has.

`.tc-rail` anchors its left edge to a viewport position so the composer and
thread do not slide sideways when the Canvas opens and narrows the column from
the right. That anchor used to be the constant `50vw - 524px`, and the comment
beside it spelled 524 out as 140 (half the sidebar) + 384 (half of a 768 wide
column). Both halves were frozen:

* Collapsing the sidebar sets `--sidebar-margin: -280px`, so it occupies no
  width - but the 140 stayed in the sum and pulled every rail 140px left of
  centre. In the desktop shell, where the sidebar is usually collapsed, that is
  the whole page sitting off to one side.
* `#tc-welcome` is 720 wide, not 768, so the 384 put the home screen 24px left
  of centre at every width, with the sidebar open or closed.

These drive the real page in headless Chromium and measure, because the bug was
invisible in the CSS text - `50vw - 524px` looks like centring, and it is, for
exactly one sidebar state and one column width.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok, open_shell  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

# Rails are `margin-right: auto`, so a rail is centred when its own centre and
# the centre of <main> agree. One pixel of slack covers subpixel rounding.
TOLERANCE = 1.0

MEASURE = """
(sel) => {
  const el = document.querySelector(sel);
  const main = document.querySelector('main');
  if (!el || !main) return null;
  const r = el.getBoundingClientRect(), m = main.getBoundingClientRect();
  if (!r.width || !m.width) return null;
  return {
    railCentre: r.left + r.width / 2,
    mainCentre: m.left + m.width / 2,
    railWidth: r.width,
    railLeft: r.left,
  };
}
"""

SET_SIDEBAR = """
(value) => {
  const shell = document.getElementById('tc-shell');
  shell.style.setProperty('--sidebar-margin', value);
  document.body.offsetWidth;   // force layout before anyone measures
}
"""

NO_MOTION = "*{transition:none !important; animation:none !important}"


@pytest.fixture(scope="module")
def shell():
    with open_shell() as s:
        yield s


def _offset(page, selector: str) -> float:
    box = page.evaluate(MEASURE, selector)
    assert box is not None, f"{selector} is not laid out"
    return box["railCentre"] - box["mainCentre"]


@pytest.mark.parametrize("state", ["0px", "-280px"])
def test_the_home_screen_is_centred_with_the_sidebar_open_or_collapsed(shell, state) -> None:
    # Boot restores the last conversation, so the thread is showing and the home
    # screen is display:none. A new chat is what puts #tc-welcome on screen, and
    # it is the rail that matters most here: at 720 it is the one width the old
    # constant got wrong even with the sidebar open.
    shell.page.add_style_tag(content=NO_MOTION)
    shell.page.click("#tc-newchat")
    shell.page.wait_for_selector("#tc-welcome", state="visible")
    shell.page.evaluate(SET_SIDEBAR, state)
    off = _offset(shell.page, "#tc-welcome")
    assert abs(off) <= TOLERANCE, f"home screen is {off:.1f}px off centre with --sidebar-margin: {state}"


@pytest.mark.parametrize("state", ["0px", "-280px"])
def test_the_composer_is_centred_with_the_sidebar_open_or_collapsed(shell, state) -> None:
    shell.page.add_style_tag(content=NO_MOTION)
    shell.page.evaluate(SET_SIDEBAR, state)
    off = _offset(shell.page, "#tc-composer-rail")
    assert abs(off) <= TOLERANCE, f"composer is {off:.1f}px off centre with --sidebar-margin: {state}"


def test_the_first_paint_is_centred_before_the_sidebar_is_ever_toggled(shell) -> None:
    """The state no test reached: `--sidebar-margin` still the markup's raw `0`.

    chat.html declares it inline as a unitless `0`, and `toggleSidebar` only
    writes `0px` or `-280px` later. A unitless zero is not a length, so the
    anchor's calc would be invalid on first paint, the whole rule would be
    dropped, and the rails would land centred only by accident - on the inline
    `margin: 0 auto` they happen to carry. `@property` makes that impossible:
    a non-length is invalid at computed-value time and falls back to the
    registered `0px`. This asserts the computed value, not just the position,
    because the position alone cannot tell those two causes apart.
    """
    shell.page.reload()
    shell.page.wait_for_selector("#tc-composer-rail", state="visible")
    computed = shell.page.evaluate(
        "() => getComputedStyle(document.getElementById('tc-shell'))"
        ".getPropertyValue('--sidebar-margin').trim()"
    )
    assert computed == "0px", "the registered property must coerce the markup's unitless 0"
    off = _offset(shell.page, "#tc-composer-rail")
    assert abs(off) <= TOLERANCE, f"first paint is {off:.1f}px off centre"


def test_a_rail_does_not_slide_when_the_column_narrows_from_the_right(shell) -> None:
    """The reason the anchor is viewport-relative at all.

    Opening the Canvas takes width off the right of the chat column. The rails
    must narrow in place, not slide left, or the composer walks across the
    screen every time an artifact appears.
    """
    shell.page.add_style_tag(content=NO_MOTION)
    shell.page.evaluate(SET_SIDEBAR, "-280px")
    before = shell.page.evaluate(MEASURE, "#tc-composer-rail")["railLeft"]
    shell.page.evaluate(
        "() => { const c = document.getElementById('tc-primary-column');"
        " c.style.flex = '0 0 60%'; document.body.offsetWidth; }"
    )
    after = shell.page.evaluate(MEASURE, "#tc-composer-rail")["railLeft"]
    shell.page.evaluate("() => { document.getElementById('tc-primary-column').style.flex = ''; }")
    assert abs(after - before) <= TOLERANCE, f"the composer slid {after - before:.1f}px when the column narrowed"


def test_the_anchor_is_derived_rather_than_written_down() -> None:
    """No constant that bakes in one sidebar state and one column width.

    The layout assertions above are the real proof; this one names the shape of
    the mistake so a future edit that reintroduces a magic number fails loudly
    instead of silently un-centring the page on one of the two sidebar states.
    """
    css = (
        Path(__file__).resolve().parents[1]
        / "thomas" / "server" / "web" / "css" / "chat_shell.css"
    ).read_text(encoding="utf-8")
    rail_rule = css.split("\n.tc-rail {", 1)[1].split("}", 1)[0]
    assert "524px" not in rail_rule, "the frozen 140 + 384 constant is back"
    assert "--sidebar-margin" in rail_rule, "the anchor must follow the sidebar's occupied width"
    assert "--tc-rail-w" in rail_rule, "the anchor must follow the rail's own width"
