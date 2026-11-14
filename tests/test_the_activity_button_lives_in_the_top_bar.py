"""The Activity button sits in the top bar, its drawer opens wider and has no X, and the bottom line reads only a step's face."""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"


def _read(relative: str) -> str:
    return (WEB / relative).read_text(encoding="utf-8")


def test_the_button_is_fixed_in_the_top_bar_and_the_drawer_has_no_x():
    css = _read("css/unified_code_plain.css")
    assert '[data-surface-mode="code"] .tc-code-context { position: fixed; top: 7px; right: 18px; }' in css
    assert ".tc-agents-drawer .tc-agents-close { display: none; }" in css


def test_the_activity_icon_is_a_pulse_that_redraws_on_hover():
    controls = _read("js/unified_code_controls.js")
    assert 'class="tc-act-icon"' in controls and "M3 12h4l3-7 4 14 3-7h4" in controls
    assert '<rect x="3" y="4" width="18" height="16" rx="2"/>' not in controls
    assert ".tc-code-context > button:hover .tc-act-icon path" in _read("css/unified_code_plain.css")


def test_the_drawer_opens_at_460_everywhere_it_has_a_default():
    assert "drawerWidth: 460" in _read("js/unified_code_mode.js")
    assert "--tc-code-drawer-width, 360px" not in _read("css/unified_code_mode.css")
    assert "--tc-code-drawer-width, 360px" not in _read("css/unified_code_agents.css")


def test_the_bottom_line_reads_the_summary_not_the_whole_step():
    source = _read("js/unified_code_live_view.js")
    assert "querySelector('summary')" in source
    assert ".tc-code-work-verb" in source and ".tc-code-work-detail" in source
