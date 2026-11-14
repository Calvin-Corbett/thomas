"""Three things you could not do or see in the shell, found by you using it (2026-11-09).

"I want to remove a freaking workspace and it didn't work." It worked, behind a right-click nothing on screen
mentioned, and the row it left behind said "1 hidden", which read as a fault. "I keep seeing this thing. It says canvas.
We removed the canvas thing from Thomas." And: "Did Thomas eyes need to follow you when you get close to it? That was a
thing I had. It's not there anymore."

Each was checked in the running desktop app through its bridge: Marketplace left the list through the row's own menu,
and a pointer moved near the mascot shifted its eyes toward it and back when it left.
"""

from __future__ import annotations

from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js"


def _read(name: str) -> str:
    return (JS / name).read_text("utf-8")


def test_every_workspace_row_carries_a_visible_control_that_opens_its_menu() -> None:
    arrange = _read("chat_workspace_arrange.js")
    more = arrange.split("function addMore(wrap, rerender) {", 1)[1].split("\n  function footer", 1)[0]
    assert "rowMenu(wrap, button, box.left, box.bottom + 4, rerender)" in more, "the same menu the right-click opens"
    assert "event.stopPropagation()" in more, "pressing it must not also open the workspace it sits on"
    assert "event.key === 'Enter' || event.key === ' '" in more
    assert "button[data-mode]:hover .tc-ws-more" in more and "button[data-mode]:focus-visible .tc-ws-more" in more
    assert "if (button.querySelector('.tc-ws-more')) return;" in more, "a row drawn again gets one, not two"
    footer = arrange.split("function footer(wrap, list, rerender) {", 1)[1].split("\n  }\n", 1)[0]
    assert footer.lstrip().startswith("addMore(wrap, rerender);"), "added on every draw, with or without removed rows"
    assert "{ action: 'hide', label: 'Hide from list', danger: true }" in arrange, "a built-in row can only be hidden"


def test_the_row_for_removed_workspaces_says_what_it_is() -> None:
    arrange = _read("chat_workspace_arrange.js")
    assert "`${hidden.length} removed · bring back`" in arrange
    assert "`${hidden.length} hidden`" not in arrange, '"1 hidden" read as something broken'
    assert "'Removed workspaces'" in arrange


def test_the_canvas_button_is_gone_from_chat_and_from_workspaces() -> None:
    drawer = _read("workspace_chat_drawer.js")
    sync = drawer.split("function syncPrimaryAction() {", 1)[1].split("\n  }\n", 1)[0]
    # It first stayed inside a workspace, where it read "Chat". 2026-11-10: "That's not supposed to be there."
    assert "button.style.display = 'none';" in sync
    connect = drawer.split("function connect(options) {", 1)[1].split("\n  }\n", 1)[0]
    assert "syncPrimaryAction();" in connect, "applied when the page starts, not only on the first workspace"


def test_the_mascots_eyes_follow_the_pointer_when_it_is_near() -> None:
    bot = _read("thomas_bot.js")
    assert bot.count('<span class="tb-eye" style=') == 2, "both eyes"
    look = bot.split("function look() {", 1)[1].split("\n  }\n", 1)[0]
    assert "document.querySelectorAll('.tb-eye')" in look
    assert "far > REACH || far < 1 ? ''" in look, "out of reach, the eyes look ahead again"
    assert "eye.style.translate =" in look and "style.transform" not in look, (
        "translate leaves the blink animation alone"
    )
    assert "document.addEventListener('pointermove'" in bot and "{ passive: true }" in bot
    assert "requestAnimationFrame(look)" in bot, "one frame of work however fast the pointer moves"
    assert "prefers-reduced-motion: reduce" in bot
