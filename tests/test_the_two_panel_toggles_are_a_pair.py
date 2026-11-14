"""The sidebar toggle and the side-panel toggle are one glyph, mirrored (2026-11-09).

You said: "the side panel tab on the left needs to match the one on the right." The left end of the bookmarks row drew
a font icon in its own box; the right end drew a 15px outline. They share one frame now, with the bar on opposite sides.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"


def _glyph(name: str) -> str:
    shell = (WEB / "js" / "browser_shell.js").read_text("utf-8")
    found = re.search(rf"^    {name}: '(<svg.*</svg>)',$", shell, re.M)
    assert found, name
    return found.group(1)


def test_the_two_glyphs_differ_only_in_which_side_the_bar_is_on() -> None:
    left, right = _glyph("sidebar"), _glyph("panel")
    assert 'd="M9 4v16"' in left and 'd="M15 4v16"' in right
    assert left.replace('d="M9 4v16"', "") == right.replace('d="M15 4v16"', "")


def test_the_sidebar_toggle_is_given_its_glyph_when_it_moves_to_the_bookmarks_row() -> None:
    shell = (WEB / "js" / "browser_shell.js").read_text("utf-8")
    assert "bookbar.appendChild(sidebarToggle); sidebarToggle.innerHTML = SVG.sidebar;" in shell


def test_both_buttons_are_the_same_box() -> None:
    css = (WEB / "css" / "browser_shell.css").read_text("utf-8")
    left = css[css.index("#bt-bookmarks #tc-sidebar-toggle {") :].split("}")[0]
    right = css[css.index("#bt-panelbtn {") :].split("}")[0]
    for part in ("width: 26px", "height: 26px", "border-radius: 7px"):
        assert part in left and part in right, part
    assert "#bt-bookmarks #tc-sidebar-toggle:hover { background: var(--c-hover) !important;" in css
