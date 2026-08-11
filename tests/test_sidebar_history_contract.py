"""The sidebar list behaves the same for Chat, Code and Work.

Each mode renders its own rows, so the shared behaviour — sorting, pin,
archive, rename, the hover card, the full-title tooltip, per-row running dots
and the collapse — lives in one decorator that every renderer tags into.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"


def _read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8", errors="replace")


def test_there_is_exactly_one_way_to_start_something_new() -> None:
    html = _read("chat.html")
    shell = _read("js/unified_mode_shell.js")

    # The pencil in the sidebar header did the same thing as the button.
    assert "tc-newchat-top" not in html
    assert "tc-newchat-top" not in shell
    assert html.count('id="tc-newchat"') == 1


def test_the_create_button_sits_above_the_search_box_and_is_short() -> None:
    html = _read("chat.html")

    assert html.index('id="tc-newchat"') < html.index('id="tc-search"')
    # It used to be padded to ~36px and crowded its neighbours.
    new_button = html[html.index('id="tc-newchat"'):html.index('id="tc-newchat"') + 700]
    assert "height: 30px" in new_button


def test_every_mode_tags_its_rows_for_the_shared_decorator() -> None:
    html = _read("chat.html")
    code = _read("js/unified_code_mode.js")
    work = _read("js/unified_work_mode.js")

    for source, name in ((html, "chat"), (code, "code"), (work, "work")):
        assert "historyId" in source, f"{name} rows carry no identity"
        assert "historyTime" in source, f"{name} rows carry no last-touched time"
        assert f"historyMode = '{name}'" in source
    for source in (html, code, work):
        assert "ThomasSidebarHistory" in source


def test_code_timestamps_are_parsed_not_coerced() -> None:
    code = _read("js/unified_code_mode.js")

    # The API returns ISO strings; Number() on those is NaN, which would sort
    # every code task as epoch zero.
    assert "Date.parse(row.updated_at" in code
    assert "Number(row.updated_at" not in code


def test_rows_show_a_running_dot_per_conversation() -> None:
    html = _read("chat.html")
    code = _read("js/unified_code_mode.js")
    css = _read("css/sidebar_history.css")

    # The mode tabs had an activity indicator; the list never said WHICH chat
    # or task the run belonged to.
    assert "running: active && state.running" in code
    assert "sel && state.streaming" in html
    assert ".tc-history-dot" in css


def test_the_hover_card_and_tooltip_are_restrained() -> None:
    history = _read("js/sidebar_history.js")

    assert "HOVER_DELAY" in history
    # A tooltip repeating a title you can already read is noise on every hover.
    assert "function isTruncated(" in history
    assert "if (!isTruncated(label)) return;" in history
    assert "function relativeTime(" in history


def test_last_touched_is_the_last_message_not_the_last_open() -> None:
    html = _read("chat.html")

    select = html[html.index("function selectChat(id)"):]
    select = select[:select.index("function ", 40)]
    # Opening a chat must not write it back, or every chat you glance at jumps
    # to the top of the list.
    assert "fetch(" not in select
    assert "PUT" not in select


def test_right_click_offers_the_row_actions() -> None:
    history = _read("js/sidebar_history.js")

    assert "contextmenu" in history
    for action in ("rename", "pin", "archive", "delete"):
        assert f"action: '{action}'" in history
    # Deleting reports from the response instead of assuming it worked.
    assert "if (!response.ok) throw new Error" in history
    assert "window.confirm(" in history


def test_sorting_and_archived_visibility_are_user_controlled() -> None:
    history = _read("js/sidebar_history.js")
    html = _read("chat.html")

    assert 'id="tc-history-filter"' in html
    for sort in ("recent", "created", "name"):
        assert f"id: '{sort}'" in history
    assert "showArchived" in history
    # Pins always float, whatever the sort.
    assert "if (left.pinned !== right.pinned) return left.pinned - right.pinned;" in history


def test_the_list_collapses_so_workspaces_stay_reachable() -> None:
    history = _read("js/sidebar_history.js")
    html = _read("chat.html")

    assert 'id="tc-history-collapse"' in html
    assert 'aria-controls="tc-chats"' in html
    assert "function applyCollapse(" in history
    assert "collapsed" in history


def test_every_icon_the_shell_uses_is_actually_in_the_icon_map() -> None:
    # chat_shell.css maps .ph-<name> to a literal glyph and falls back to a
    # bare bullet. Five controls shipped as unlabelled dots this way — the
    # sort button was literally a dot next to the list heading.
    css = _read("css/chat_shell.css")
    mapped = set(re.findall(r"\.(ph-[a-z0-9-]+)::before", css))

    used: set[str] = set()
    sources = [WEB / "chat.html"] + sorted((WEB / "js").glob("*.js"))
    for path in sources:
        used |= set(re.findall(r"\bph-[a-z0-9-]+\b", path.read_text(encoding="utf-8", errors="replace")))
    # Names built at runtime from user/model input are validated elsewhere.
    used -= {"ph-caret", "ph-circle"}

    missing = sorted(name for name in used if name not in mapped)
    assert not missing, f"these render as a bare dot: {missing}"


def test_the_sort_control_names_itself() -> None:
    html = _read("chat.html")
    history = _read("js/sidebar_history.js")

    # A bare icon was a control nobody could read; it now shows the sort in use.
    assert 'id="tc-history-sort-label"' in html
    assert "function syncSortLabel(" in history
    for short in ("'Recent'", "'Created'", "'Name'"):
        assert f"short: {short}" in history
    # And no meaningless dot for unselected options.
    assert "ph-dot" not in history
    assert "tc-history-menu-gap" in history


def test_pressing_the_sort_button_again_closes_it() -> None:
    history = _read("js/sidebar_history.js")

    assert "menuOwner" in history
    assert "if (menuOwner === 'filter') { closeMenu(); return; }" in history


def test_a_date_ordered_list_reads_as_days() -> None:
    history = _read("js/sidebar_history.js")
    css = _read("css/sidebar_history.css")

    assert "function dayLabel(" in history
    assert "'Today'" in history and "'Yesterday'" in history
    assert "function dayHeading(" in history
    # Headings only when the order IS chronological — under a name sort they
    # would be meaningless.
    assert "spec.dated" in history
    assert "dated: false" in history
    assert ".tc-history-day" in css


def test_titles_are_generated_only_where_they_are_needed() -> None:
    history = _read("js/sidebar_history.js")

    assert "function looksRaw(" in history
    assert "titledThisSession" in history
    assert "/api/chats/title" in history
    # A name the user typed always wins over a generated one.
    assert "if ((overlay()[id] || {}).title) return;" in history


def test_titling_has_a_hard_budget_and_cannot_walk_the_whole_history() -> None:
    history = _read("js/sidebar_history.js")

    # Writing titles refreshes the list, which re-decorates, which started the
    # next batch. With 476 rows that made 88 model calls in four minutes on the
    # user's account. A per-row guard does not bound this; a budget does.
    assert "SESSION_BUDGET" in history
    assert "let titleBudget = SESSION_BUDGET;" in history
    assert "if (titleRunning || titleBudget <= 0) return;" in history
    assert "titleBudget -= pending.length;" in history
    assert "Math.min(BATCH_SIZE, titleBudget)" in history
    # And only rows that are actually on screen are worth paying to name.
    assert "function onScreen(" in history
    assert "onScreen(row, wrap)" in history


def test_a_generated_title_is_a_name_not_a_sentence() -> None:
    from thomas.server.routes.chat_titles_runtime import _clean_title

    assert _clean_title('"Login redirect loop"') == "Login redirect loop"
    assert _clean_title("Login redirect loop.") == "Login redirect loop"
    # Too long, or a sentence, is worse than the raw prompt because it looks
    # deliberate — rejected rather than truncated into nonsense.
    assert _clean_title("This is a much longer sentence that is really a description") == ""
    assert _clean_title("") == ""


def test_hovering_a_row_cannot_move_the_list() -> None:
    css = _read("css/sidebar_history.css")
    history = _read("js/sidebar_history.js")

    # Revealing the time used to insert a line, changing the row's height. On a
    # fast scroll that reflowed rows under the cursor and read as overlap.
    assert ".tc-history-sub" in css
    assert "height: 16px" in css
    assert "[data-history-id]:hover .tc-history-meta" in css
    # And the swap is pure CSS, so nothing runs per row while it scrolls.
    assert "meta.hidden = false" not in history
    assert "meta.hidden = true" not in history


def test_the_sticky_date_heading_is_opaque() -> None:
    css = _read("css/sidebar_history.css")

    # --c-sidebar is rgba(...,0.72); painting a sticky heading with it lets
    # rows scroll straight through it.
    day = css[css.index(".tc-history-day {"):]
    day = day[:day.index("}")]
    assert "linear-gradient(var(--c-sidebar), var(--c-sidebar)), var(--c-bg)" in day
    assert "transparent" not in day


def test_the_sidebar_controls_are_drawn_not_glyphs() -> None:
    html = _read("chat.html")

    head = html[html.index('class="tc-history-head"'):html.index('id="tc-chats"')]
    # The icon map's caret is "\2304", a thin stray mark, and its funnel did
    # not exist at all. Both are inline SVG now.
    assert "<svg" in head
    assert 'id="tc-history-collapse-icon"' in html
    assert "ph-caret-down" not in head
    assert "ph-funnel-simple" not in head


def test_undo_is_always_offered_and_says_why_when_it_cannot_run() -> None:
    select = _read("js/ui_redesign_select.js")

    assert "REWIND_ICON" in select
    # Always rendered — disabled with a reason beats appearing out of nowhere.
    assert 'data-tr="revert"' in select
    assert "Pick something you changed to undo it" in select
    assert "Nothing to undo on what you picked" in select
    # A change made before per-element history existed still undoes, by
    # clearing the entry back to the authored look.
    assert "layout.remove(id);" in select


def test_the_redesign_cursor_is_a_blacksmith_hammer() -> None:
    css = _read("css/ui_redesign.css")

    cursor = css[css.index("html.tr-selecting,"):]
    cursor = cursor[:cursor.index("}")]
    assert "image/svg+xml" in cursor
    # Chunky head with the handle passing through it, tilted, small wedge peen.
    # Thin-head versions read as a pickaxe and then as a flag on a pole.
    assert "M4 4h20l4 3v2l-4 3H4Z" in cursor
    assert "rotate(-20 16 16)" in cursor
    # Hotspot on the striking face, so you hit what you point at.
    assert "') 3 14," in cursor


def test_the_modes_are_three_faces_of_thomas() -> None:
    html = _read("chat.html")
    icons = _read("js/thomas_icons.js")

    # The head with two eyes IS the Thomas mark; each mode wears a tool, so the
    # tabs read as aspects of one product rather than three unrelated buttons.
    assert "const HEAD =" in icons and "const EYES =" in icons
    for mode, tool in (("chat", "chat"), ("code", "build"), ("work", "work")):
        tab = html[html.index(f'data-thomas-mode="{mode}"'):]
        tab = tab[:tab.index("</button>")]
        assert f'data-thomas-icon="{tool}"' in tab
        assert "ph-" not in tab, f"{mode} still uses a Unicode stand-in"
    # Build wears a hammer, not an anvil.
    build = icons[icons.index("build: HEAD"):icons.index("work: HEAD")]
    assert "rotate(-22 12 12)" in build

    # The sidebar header stays the Thomas mark.
    header = html[html.index('class="tc-sidebar"'):html.index('id="tc-mode-switch"')]
    assert "<svg" not in header


def test_code_is_called_build_but_keeps_its_adapter_id() -> None:
    shell = _read("js/unified_mode_shell.js")
    html = _read("chat.html")

    cfg = shell[shell.index("code: {"):shell.index("};", shell.index("code: {"))]
    assert "label: 'Build'" in cfg
    assert "history: 'Builds'" in cfg
    assert "create: 'New build'" in cfg
    # The key is the adapter id, the surface-mode attribute and half the API's
    # vocabulary — renaming it would unwire the mode, not relabel it.
    assert "code: {" in shell
    assert 'data-thomas-mode="code"' in html


def test_the_sidebar_has_no_unicode_stand_in_icons_left() -> None:
    html = _read("chat.html")
    icons = _read("js/thomas_icons.js")

    sidebar = html[html.index('class="tc-sidebar"'):html.index("</aside>")]
    assert 'class="ph ph-' not in sidebar, "a Unicode stand-in survives in the sidebar"
    # Every workspace row names a drawn glyph that actually exists.
    for name in re.findall(r"\{ icon: '([a-z]+)',", html):
        assert f"{name}:" in icons, f"workspace icon {name!r} is not defined"


def test_browser_only_overrides_say_so() -> None:
    history = _read("js/sidebar_history.js")

    # Rename/pin/archive are a localStorage overlay, not a schema change in
    # three stores. The menu has to admit that rather than imply they sync.
    assert "OVERLAY_KEY" in history
    assert "saved in this browser" in history
