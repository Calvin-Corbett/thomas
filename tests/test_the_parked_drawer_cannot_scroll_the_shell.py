"""A drawer parked off-screen must not let the whole shell scroll sideways (2026-09-05).

Measured on the Build tab after a reload: ``#tc-shell`` was 2089 px wide at a
1280 px viewport, scrolled 51 px to the left, and the sidebar's first letters
were cut off. The width came from ``#tc-workspace-chat-drawer``, parked with
``transform: translateX(102%)`` -- a transformed box still extends its
container's scrollable overflow, and the shell's inline ``overflow: hidden``
only hides the scrollbar: a focus() or scrollIntoView() in the composer can
still scroll it, and did. ``overflow-x: clip`` forbids that scrolling; it has to
be ``!important`` because the shell's overflow is an inline style.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "thomas" / "server" / "web" / "css" / "workspace_chat_drawer.css"


def test_the_shell_clips_horizontal_overflow_with_priority_over_its_inline_style() -> None:
    source = CSS.read_text(encoding="utf-8")
    rule = re.search(r"#tc-shell\s*\{([^}]*)\}", source)
    assert rule, "no #tc-shell rule beside the drawer that causes the overflow"
    # Both axes: `overflow-x: clip` beside an inline `overflow-y: hidden` computes back to
    # hidden (one axis may not be clip while the other scrolls), measured live before this.
    assert re.search(r"(?<!-x)(?<!-y)overflow\s*:\s*clip\s*!important", rule.group(1)), rule.group(1)


def test_the_drawer_still_parks_by_transform_so_the_slide_in_is_kept() -> None:
    source = CSS.read_text(encoding="utf-8")
    assert "transform: translateX(102%)" in source
