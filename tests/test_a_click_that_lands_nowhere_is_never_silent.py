"""Three separate bugs made the browser's clicks land nowhere, and every one
of them failed in silence: the call returned success, the page did not move,
and nothing anywhere said why.

They were expensive to find precisely because a DOM read still worked in all
three states -- `read_dom` happily returns a page's text from a view with a
0x0 viewport, so every read-based check passed while every click failed.
These tests pin the fixes against the shipped source so the silence cannot
come back.

The three causes, for whoever reads this next:
  1. `DOM.getBoxModel` returns coordinates that can disagree with the
     viewport the input dispatcher aims at (wikipedia's circular link layout
     produced x=-100, y=-437).
  2. A `ResizeObserver` fires once immediately, and before first layout that
     rect is 0x0 -- accepting it sized the web view to nothing.
  3. A hidden background tab also has a 0x0 viewport, so acting on one did
     nothing at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MAIN_JS = REPO / "desktop" / "main.js"
SHELL_JS = REPO / "thomas" / "server" / "web" / "js" / "browser_shell.js"

pytestmark = pytest.mark.skipif(not MAIN_JS.exists(), reason="desktop shell is not present in this checkout")


def _main() -> str:
    return MAIN_JS.read_text(encoding="utf-8")


def test_click_points_come_from_the_element_not_the_box_model() -> None:
    src = _main()
    assert "getBoundingClientRect" in src, "click point must come from the element itself"
    assert "scrollIntoView" in src, "the element must be scrolled into view first"
    # The box model may still be read elsewhere, but never to aim a click.
    assert "clickPointOf" in src and "dispatchClick" in src, "clicking must go through one shared path"


def test_a_name_on_a_text_node_still_finds_something_clickable() -> None:
    """Accessible names often belong to text nodes or zero-size wrappers."""
    src = _main()
    assert "parentElement" in src, "must climb to an ancestor with area"
    assert "nodeType === 3" in src, "must handle a text node"


def test_an_element_with_no_area_is_refused_rather_than_clicked() -> None:
    src = _main()
    assert "no clickable area" in src


def test_a_zero_size_rect_is_never_accepted_as_bounds() -> None:
    """Both ends refuse it: the page must not send one, main must not store one."""
    assert "rect.width <= 0 || rect.height <= 0" in _main(), "main must refuse a zero rect"
    shell = SHELL_JS.read_text(encoding="utf-8")
    assert "r.width <= 0 || r.height <= 0" in shell, "the page must not report a zero rect"


def test_acting_on_a_background_tab_brings_it_forward() -> None:
    """A hidden view has a 0x0 viewport, so a click on one does nothing."""
    src = _main()
    assert "forTabInteractive" in src
    # Both click verbs must use it; a read verb deliberately need not.
    click_block = src[src.index("    click: async p =>") : src.index("    url: async p =>")]
    assert click_block.count("forTabInteractive") >= 2, "both click verbs must activate the tab"


def test_a_missed_anchor_is_reported_not_approximated() -> None:
    """Clicking 'whatever was nearby' is worse than admitting the miss."""
    src = _main()
    assert 'throw new Error(`no ${role || "element"} named' in src


def test_the_failure_says_the_numbers() -> None:
    """A bare 'outside the viewport' sent the last debugger guessing twice."""
    src = _main()
    assert "sits outside the viewport after scrolling" in src
    for evidence in ("point ", "point.vw", "point.tag"):
        assert evidence in src, f"the error must carry {evidence}"
    assert "metrics: async p" in src, "geometry must be inspectable from the bridge"
