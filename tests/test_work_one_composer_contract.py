"""Work mode has ONE composer, a peek strip, and an addressable surface.

Work used to render its own composer inside the job surface while the shell
composer sat below it, so "which box do I type in?" was a real question with
two real answers. These are regression guards: the second composer is gone,
the peek strip is the only conversation shown beside the shell composer, and
every dashboard item carries the spec address a targeted redesign patches by.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_work_renders_no_composer_of_its_own() -> None:
    support = _read(WEB / "js" / "unified_work_support.js")
    mode = _read(WEB / "js" / "unified_work_mode.js")
    css = _read(WEB / "css" / "unified_work_mode.css")

    # The element, its handler block, and its styling all had to go — a
    # leftover rule is how a deleted surface quietly comes back. The CSS is
    # matched as a selector so the tombstone comment naming it still passes.
    assert "tc-work-composer" not in support
    assert "tc-work-composer" not in mode
    assert not re.search(r"^\.tc-work-composer", css, re.MULTILINE)
    assert "composerHtml" not in support
    assert "composerHtml" not in mode


def test_shell_has_exactly_one_composer_and_one_peek_slot() -> None:
    html = _read(WEB / "chat.html")

    assert html.count('id="tc-input"') == 1
    assert html.count('id="tc-mode-peek"') == 1
    # The peek slot must sit above the composer: that ordering is what makes
    # a second composer impossible to add without noticing.
    assert html.index('id="tc-mode-peek"') < html.index('id="tc-input"')


def test_peek_shows_only_the_last_exchange() -> None:
    support = _read(WEB / "js" / "unified_work_support.js")
    css = _read(WEB / "css" / "mode_peek.css")

    assert "function peekRows()" in support
    assert ".slice(-2)" in support
    assert "row.role !== 'system'" in support
    assert "-webkit-line-clamp: 2" in css
    assert "mask-image" in css


def test_typing_does_not_throw_the_user_into_the_chat_tab() -> None:
    mode = _read(WEB / "js" / "unified_work_mode.js")

    # Chatting while reading the dashboard is the entire point of the strip.
    assert "if (state.stage === 'job') state.dashTab = 'chat';" not in mode
    assert "state.dashTabBeforeChat" in mode
    assert "function setChatExpanded" in mode


def test_chat_tab_survives_as_a_real_destination() -> None:
    support = _read(WEB / "js" / "unified_work_support.js")

    assert "{ id: 'chat', label: 'Chat' }" in support
    assert 'id="tc-work-conversation"' in support
    assert "data-work-collapse-chat" in support


def test_expand_animates_and_respects_reduced_motion() -> None:
    peek = _read(WEB / "js" / "mode_peek.js")

    assert "prefers-reduced-motion: reduce" in peek
    assert "element.animate" in peek
    assert "function transition" in peek


def test_workflow_rail_is_a_list_and_setup_owns_configuration() -> None:
    support = _read(WEB / "js" / "unified_work_support.js")

    rail_start = support.index("function workflowRailHtml()")
    rail_end = support.index("function workflowsSetupHtml()")
    rail = support[rail_start:rail_end]

    for banished in ("Add workflow", "Selected workflow", "Configure ", "Mark ready", "Run once"):
        assert banished not in rail, f"{banished!r} still lives in the rail"

    setup = support[support.index("function workflowsSetupHtml()"):support.index("function jobHtml()")]
    for kept in ("Mark ready", "Run once", "Add workflow", "Configure "):
        assert kept in setup, f"{kept!r} was lost instead of moved"
    assert "workflowsSetupHtml()" in support[support.index("function setupTabHtml()"):]


def test_every_dashboard_item_carries_a_spec_address() -> None:
    support = _read(WEB / "js" / "unified_work_support.js")

    assert "function specAttrs(" in support
    for kind in ("'metric'", "'widget'", "'sheet'", "'section'", "'inbox'", "'action'", "'tab'", "'headline'"):
        assert f"specAttrs({kind}" in support, f"no spec address emitted for {kind}"
    # Indices must come from the SAVED array, not from the per-tab filter,
    # or the server would patch a different row than the one clicked.
    assert ".map((row, index) => ({ row, index }))" in support


def test_work_surface_is_addressable_by_the_ui_editor() -> None:
    support = _read(WEB / "js" / "unified_work_support.js")

    # Work rendered zero data-ui-id regions before this, so Ctrl+Shift+E and
    # Redesign were both blind to the entire mode.
    assert support.count("data-ui-id") >= 8
    for region in ("work.job.rail", "work.job.main", "work.job.tabs", "work.job.conversation"):
        assert region in support


def test_redesign_is_global_chrome_not_a_dashboard_footer() -> None:
    html = _read(WEB / "chat.html")
    support = _read(WEB / "js" / "unified_work_support.js")

    assert 'id="tc-redesign-btn"' in html
    assert 'data-ui-id="chat.action.redesign"' in html
    # The old footer button re-rolled the whole dashboard with no instruction.
    assert "Redesign with AI" not in support
    assert "tc-work-dash-foot" not in support
    # The empty-state generator is a different thing and stays.
    assert "Design my dashboard" in support
