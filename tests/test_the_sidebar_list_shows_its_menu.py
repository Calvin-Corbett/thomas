"""The sidebar list shows that a row has a menu, offers only what works, and says what Thomas answered (2026-11-09).

Found by using the running app. Test chats ("Ready", "pong", "1,2,3") sat beside real ones and the only way to remove
one was a right-click that nothing on screen mentioned. A row's second line repeated its first, because both came from
the first thing you typed. And the cost line under the composer read "6.1k in" for a one-word message with no word of
why. You said: "you're going to see a lot of stuff that's probably wrong ... So you go ahead and fix those too."
"""

from __future__ import annotations

from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js"


def _read(name: str) -> str:
    return (JS / name).read_text("utf-8")


def _body(source: str, opening: str) -> str:
    """The text of the function that starts with ``opening``, up to the next function at the same depth."""
    return source.split(opening, 1)[1].split("\n  function ", 1)[0]


def test_every_decorated_row_gets_a_visible_control_that_opens_the_same_menu() -> None:
    history = _read("sidebar_history.js")
    assert "addMoreControl(row);" in _body(history, "function decorateRow(row) {")
    more = _body(history, "function addMoreControl(row) {")
    assert "more.setAttribute('role', 'button')" in more and "more.setAttribute('tabindex', '0')" in more
    assert "more.setAttribute('aria-haspopup', 'menu')" in more
    assert "openMenu(row, rect.left, rect.bottom + 4)" in more, "the same menu the right-click opens"
    assert "event.stopPropagation()" in more, "pressing it must not also open the chat it sits on"
    assert "event.key === 'Enter' || event.key === ' '" in more, "and it works from the keyboard"
    assert "row.querySelector('[data-history-more]')" in more, "a row decorated twice gets one, not two"


def test_the_control_shows_on_hover_and_on_keyboard_focus() -> None:
    more = _body(_read("sidebar_history.js"), "function addMoreControl(row) {")
    assert "opacity:0" in more
    assert "[data-history-id]:hover .tc-history-more" in more
    assert "[data-history-id]:focus-within .tc-history-more" in more


def test_the_menu_offers_only_what_works_for_that_kind_of_row() -> None:
    items = _body(_read("sidebar_history.js"), "function menuItems(row) {")
    assert ".filter(item => !item.only || item.only.includes(mode))" in items
    for action in ("export", "snapshot", "branch"):
        line = next(row for row in items.splitlines() if f"action: '{action}'" in row)
        assert "only: ['chat']" in line, f"{action} is for chats"
    delete = next(row for row in items.splitlines() if "action: 'delete'" in row)
    assert "only: ['chat', 'code']" in delete, "a Work job has no delete route behind this menu"
    for action in ("rename", "pin", "archive"):
        line = next(row for row in items.splitlines() if f"action: '{action}'" in row)
        assert "only:" not in line, f"{action} is saved in the browser and works for every row"


def test_a_chat_rows_second_line_is_what_thomas_answered_not_what_you_typed() -> None:
    view = _read("chat_history_view.js")
    to_list = view.split("function toList(rows) {", 1)[1].split("function remember(rows)", 1)[0]
    assert "msgs.filter(m => m.role === 'assistant' && String(m.text || '').trim()).pop()" in to_list
    assert "row.preview || (lastReply ? lastReply.text : '')" in to_list
    assert "firstUser" not in to_list, "the first message is the title's source; repeating it under itself said nothing"


def test_the_cost_line_says_why_a_short_message_reads_thousands_of_tokens() -> None:
    cost = _read("cost_readout.js")
    title = cost.split("el.title = ", 1)[1].split(";\n", 1)[0]
    assert "standing instructions" in title and "list of tools" in title
    assert "cached" in title


def test_no_message_in_the_build_files_calls_the_mode_code() -> None:
    import re

    old = re.compile(
        r"\bCode (tasks?|history|request|approval|result|reply|status|turn|project|API|conversation|run|activity)\b"
    )
    for path in sorted(JS.glob("unified_code_*.js")):
        found = [line.strip()[:120] for line in path.read_text("utf-8").splitlines() if old.search(line)]
        assert not found, f"{path.name} still calls Build by its old name: {found[:3]}"
    assert "label: 'Build'" in _read("unified_mode_shell.js")
