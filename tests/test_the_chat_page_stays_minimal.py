"""The chat page keeps the minimal layout you asked for, and it cannot quietly come back.

Your direction, 2026-09-06: "We are going minimal: remove the whole brand header
in the sidebar, the face icon and the word Thomas, there are two icons on the
left and we want one; keep the Chat/Build/Work switch. ... Remove the welcome
tiles on a new chat entirely, including Draw it on the canvas; a new chat is
just the greeting and the composer."

It was applied to your personal overlay, then cleared 72 seconds later on the
promise that "Thomas is making the same change in stock". The stock change never
happened, and both came back. These make the next refactor of this page fail a
test instead of silently undoing what you chose.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"


def _sidebar_before_the_switch() -> str:
    html = (WEB / "chat.html").read_text(encoding="utf-8")
    start = html.index('class="tc-sidebar"')
    return html[start : html.index('id="tc-mode-switch"', start)]


def test_the_sidebar_has_no_brand_header() -> None:
    head = _sidebar_before_the_switch()
    assert not re.search(r">\s*Thomas\s*<", head), "the word Thomas is back at the top of the sidebar"
    assert "c-accent-ink" not in head, "the face mark is back at the top of the sidebar"


def test_the_chat_build_work_switch_is_kept() -> None:
    html = (WEB / "chat.html").read_text(encoding="utf-8")
    for mode in ("chat", "code", "work"):
        assert f'data-thomas-mode="{mode}"' in html


def test_a_new_chat_has_no_welcome_tiles() -> None:
    js = (WEB / "js" / "chat_history_view.js").read_text(encoding="utf-8")
    start = js.index("function renderCards(")
    body = js[start : js.index("\n    }\n", start)]
    for tile in ("Draw it on the canvas", "Make a document", "Chart some data", "Write & run code"):
        assert tile not in body, f"the {tile!r} tile is back"
    assert "hv-card" not in body, "renderCards builds tiles again"
