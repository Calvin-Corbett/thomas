"""The row beside the Activity button: the lead's context use reaches the page, and the row is wired in."""

from __future__ import annotations

import json
from pathlib import Path

from thomas.core.events import EventType
from thomas.forge.anvil import run_control
from thomas.forge.anvil.dispatch_agent_loop_translator import _AgentLoopForgeTranslator

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"


def test_context_use_is_recorded_and_served_in_the_snapshot(tmp_path):
    run_control.write_context(tmp_path, 142_000, 400_000)

    assert json.loads((tmp_path / "context.json").read_text(encoding="utf-8"))["tokens"] == 142_000
    reading = {"tokens": 142_000, "window": 400_000, "model_window": 400_000, "breakdown": []}
    assert run_control.read_context(tmp_path) == reading
    assert run_control.snapshot(tmp_path, running=True)["context"] == reading


def test_a_nonsense_reading_is_never_recorded_and_no_reading_is_none(tmp_path):
    run_control.write_context(tmp_path, -5, 400_000)
    run_control.write_context(tmp_path, 10, 0)
    run_control.write_context(tmp_path, "many", 400_000)

    assert run_control.read_context(tmp_path) is None
    assert run_control.snapshot(tmp_path, running=False)["context"] is None


def test_the_lead_translator_hands_each_iteration_to_its_sink():
    seen: list[tuple[object, object]] = []
    translator = _AgentLoopForgeTranslator(lambda event: None)
    translator.context_sink = lambda tokens, window, breakdown: seen.append((tokens, window))

    translator.feed(EventType.AGENT_ITERATION.value, {"token_estimate": 9000, "context_window": 400_000})
    translator.feed(EventType.AGENT_ITERATION.value, {"token_estimate": 12_000, "context_window": 400_000})

    assert seen == [(9000, 400_000), (12_000, 400_000)]


def test_a_translator_without_a_sink_ignores_iterations():
    translator = _AgentLoopForgeTranslator(lambda event: None)
    translator.feed(EventType.AGENT_ITERATION.value, {"token_estimate": 1, "context_window": 2})


def test_a_tile_is_a_live_miniature_with_a_type_label_and_opens_focused_in_the_middle():
    source = (WEB / "js" / "unified_code_header.js").read_text(encoding="utf-8")
    css = (WEB / "css" / "unified_code_header.css").read_text(encoding="utf-8")
    assert 'class="tc-dash-frame"' in source and "state.artifactDocs" in source  # the page's own prepared document
    assert "KIND_LABEL" in source and ".tc-dash-tile:hover .tc-dash-kind" in css  # what kind of file, on hover
    assert "function focus(" in source and "tc-dash-focus-card" in source  # one output, large, centred
    assert "card.focus(" in source and "frame.focus(" not in source  # a game's frame must not swallow Escape
    assert "display: grid; place-items: center" in css and "position: fixed; inset: 0" in css


def test_the_context_meter_is_always_there_in_an_open_task_and_loads_the_last_runs_reading():
    source = (WEB / "js" / "unified_code_header.js").read_text(encoding="utf-8")
    assert "No reading yet." in source and "is-empty" in source  # an empty meter, never nothing
    # Used, not left: just the percent, coloured from green to red as the window fills.
    assert "left</span>" not in source and "fillColor(used)" in source and "${pct}%</span>" in source
    # Click it and a panel stacks under the Steps card, with where the tokens went and a Compact button.
    assert "data-ctx-toggle" in source and "data-ctx-panel" in source and "data-ctx-compact" in source
    assert "/api/evolve/agent/compact" in source and "breakdown" in source
    assert "function loadContext()" in source and "/api/evolve/agent/messages?run_id=" in source
    assert "asked.has(state.activeId)" in source  # asked once per task, not on every repaint


def test_the_total_is_a_button_that_opens_a_slider_in_25k_steps_and_the_choice_sticks():
    source = (WEB / "js" / "unified_code_header.js").read_text(encoding="utf-8")
    css = (WEB / "css" / "unified_code_header.css").read_text(encoding="utf-8")
    assert "data-ctx-window" in source and 'type="range"' in source and "const STEP = 25000" in source
    assert "/api/evolve/agent/context-window" in source and "data-ctx-reset" in source  # applied on release, resettable
    assert "if (panel && !sliding)" in source  # the panel is not redrawn under the thumb
    assert "applySavedWindow();" in source and "thomas_context_window" in source  # sent to each new run
    assert ".tc-ctx-window:hover" in css and ".tc-ctx-slider input" in css


def test_activity_opens_as_a_bubble_under_the_top_bar_and_takes_no_column():
    css = (WEB / "css" / "unified_code_header.css").read_text(encoding="utf-8")
    js = (WEB / "js" / "unified_code_header.js").read_text(encoding="utf-8")
    assert "inset: var(--tc-code-stack-bottom, 64px) 14px auto auto" in css  # under whatever the bar holds
    assert "--tc-code-col-reserve: 0px" in css and ".tc-code-drawer-resize { display: none; }" in css
    assert "--tc-code-stack-bottom" in js and "ResizeObserver" in js  # follows the bar as panels open and close


def test_the_row_is_loaded_rendered_and_opens_files_through_the_viewer():
    html = (WEB / "chat.html").read_text(encoding="utf-8")
    assert "/static/css/unified_code_header.css" in html and "/static/js/unified_code_header.js" in html
    surface = (WEB / "js" / "unified_code_surface.js").read_text(encoding="utf-8")
    assert "ThomasCodeHeader.rowHtml(" in surface and "ThomasCodeHeader.open =" in surface
    controls = (WEB / "js" / "unified_code_controls.js").read_text(encoding="utf-8")
    assert "state.contextUse = {" in controls


def test_opening_or_starting_a_task_clears_the_old_one_at_once():
    surface = (WEB / "js" / "unified_code_surface.js").read_text(encoding="utf-8")
    projects = (WEB / "js" / "unified_code_projects.js").read_text(encoding="utf-8")
    assert "const turns = !opening &&" in surface and "const liveEvents = opening ? [] :" in surface
    assert (
        "state.openingConversationId = '__new__';" in projects
    )  # a new task blanks the old at the click, not after the server answers


def test_the_page_starts_its_slow_loads_before_the_scripts_run():
    html = (WEB / "chat.html").read_text(encoding="utf-8")
    assert (
        '<link rel="preload" as="fetch" crossorigin href="/api/chats?mode=chat">' in html
    )  # the sidebar list starts early
    assert (
        'browser_shell_"+n+".js' in html and "browser_shell.css" in html
    )  # the chrome's eight scripts download together


def test_the_sidebar_list_is_shown_from_the_last_visit_while_the_fresh_one_loads():
    source = (WEB / "js" / "chat_history_view.js").read_text(encoding="utf-8")
    assert "thomas_recent_chats_v1" in source and "paintRemembered();" in source and "remember(rows);" in source


def test_the_model_list_and_project_names_are_shown_from_the_last_visit_first():
    picker = (WEB / "js" / "chat_model_picker.js").read_text(encoding="utf-8")
    projects = (WEB / "js" / "unified_code_projects.js").read_text(encoding="utf-8")
    assert "thomas_models_catalog_v1" in picker and "thomas_project_names_v1" in projects


def test_repeat_reads_of_three_endpoints_share_one_answer_and_load_first():
    html = (WEB / "chat.html").read_text(encoding="utf-8")
    source = (WEB / "js" / "fetch_share.js").read_text(encoding="utf-8")
    assert html.index("fetch_share.js") < html.index("workspace_shell.js")  # in place before anything asks
    assert r"marketplace\/installed|health|settings\/index\/cards" in source and "method !== 'GET'" in source
    assert "response.clone()" in source  # every caller reads its own copy


def test_the_sidebar_makes_one_date_formatter_per_style_not_one_per_row():
    source = (WEB / "js" / "sidebar_history.js").read_text(encoding="utf-8")
    assert "new Intl.DateTimeFormat" in source and ".toLocaleDateString(" not in source


def test_a_new_tab_shows_a_loading_screen_until_its_page_is_ready():
    docs = (WEB / "js" / "browser_shell_docs.js").read_text(encoding="utf-8")
    css = (WEB / "css" / "browser_shell.css").read_text(encoding="utf-8")
    assert 'loader.className = "bt-doc-loading"' in docs and "tab.loader.remove()" in docs
    assert (
        docs.count("loader.classList") + docs.count("tab.loader.classList") >= 2
    )  # shown with the tab, hidden with it
    assert ".bt-doc-loading.is-active { display: flex; }" in css


def test_build_asks_for_the_slim_task_list_and_a_task_draws_only_its_newest_turns():
    mode = (WEB / "js" / "unified_code_mode.js").read_text(encoding="utf-8")
    surface = (WEB / "js" / "unified_code_surface.js").read_text(encoding="utf-8")
    rows = (WEB / "js" / "unified_code_history_rows.js").read_text(encoding="utf-8")
    sidebar = (WEB / "js" / "sidebar_history.js").read_text(encoding="utf-8")
    assert "agent/conversations?slim=1" in mode and "ThomasCodeLoading.show()" in mode
    assert "const KEEP = 8;" in surface and "data-code-earlier" in surface and "index < firstShown" in surface
    assert "root.dataset.listSig" in rows and "node.dataset.sig !== signature" in rows
    assert "function placeInOrder" in sidebar and "clearHeadings" not in sidebar
