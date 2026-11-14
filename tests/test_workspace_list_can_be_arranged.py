"""The Workspaces list in the sidebar can be arranged: dragged, renamed, removed.

You asked for exactly this: "click and drag a workspace and organize it however
you want", "right click on workspaces to remove them. Or to rename them", and a
list that scrolls. The behaviour lives in chat_workspace_arrange.js; the list is
still built by chat_workspace_navigation.js. These checks keep the two joined, in
the order the page loads them, so the gestures cannot quietly come apart from the
rows they act on.
"""

from __future__ import annotations

from pathlib import Path

from tests.web_fixtures.chat_sources import read_chat_sources

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"


def _read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8", errors="replace")


def test_the_arrange_module_loads_before_the_list_that_uses_it() -> None:
    html = read_chat_sources(WEB / "chat.html")

    arrange = html.index("chat_workspace_arrange.js")
    navigation = html.index("chat_workspace_navigation.js")
    assert arrange < navigation, "the list renders on load and would miss the gestures"


def test_every_row_is_a_draggable_with_its_mode_on_it() -> None:
    nav = _read("js/chat_workspace_navigation.js")

    assert "b.dataset.mode = w.mode" in nav
    assert "b.draggable = true" in nav
    # Both the built-in rows and plugin rows (Phone) go through the one arrange step.
    assert "arrangeApi.arrange(workspaces)" in nav
    assert "arrangeApi.attach(wrap, renderWorkspaces)" in nav
    assert "arrangeApi.footer(wrap, workspaces, renderWorkspaces)" in nav


def test_the_gestures_are_all_there() -> None:
    arrange = _read("js/chat_workspace_arrange.js")

    for gesture in ("'dragstart'", "'dragover'", "'drop'", "'contextmenu'"):
        assert gesture in arrange, f"{gesture} is not handled"
    for action in ("rename", "hide", "show", "reset"):
        assert f"'{action}'" in arrange, f"the {action} action is missing"
    # The keyboard reaches the same things.
    assert "event.altKey" in arrange and "'F2'" in arrange


def test_removing_hides_a_workspace_and_never_uninstalls_it() -> None:
    arrange = _read("js/chat_workspace_arrange.js")

    assert "state.hidden.push(mode)" in arrange
    assert "fetch(" not in arrange, "arranging the list must not call the server"
    assert "it is not uninstalled" in arrange


def test_rename_does_not_use_the_prompt_the_desktop_window_refuses() -> None:
    arrange = _read("js/chat_workspace_arrange.js")

    assert "prompt(" not in arrange
    assert "tc-ws-rename" in arrange


def test_a_workspace_the_saved_order_has_not_seen_still_shows() -> None:
    arrange = _read("js/chat_workspace_arrange.js")

    # Phone is installed after you arrange the list; it must appear, not vanish.
    assert "const fresh = list.filter((w) => !rank.has(w.mode))" in arrange
    assert "placed.concat(fresh)" in arrange


def test_the_list_scrolls_and_keeps_the_wheel() -> None:
    css = _read("css/sidebar_history.css")

    block = css[css.index("#tc-workspaces {") :]
    block = block[: block.index("}")]
    assert "overflow-y: auto" in block
    assert "overscroll-behavior: contain" in block
    assert "min-height: 0" in block
