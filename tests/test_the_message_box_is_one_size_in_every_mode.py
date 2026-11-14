"""The message box is the same width, in the same place, in Chat, Build and Work (2026-11-10).

You said: "the composer for a build is wider and further to the bottom than the other ones. And the other one says
Thomas can make mistakes. The build one doesn't say that. Well, we want to save space and make it wider."

Every mode takes Build's 860px measure and Build's 256px sidebar, and the line of small print is gone from all three.
A sidebar width you set with Redesign is left alone: outside Build the 256px applies only while the sidebar still
carries the width the page ships with.
"""

from __future__ import annotations

from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "css"


def test_every_mode_shares_one_measure_and_the_small_print_is_gone() -> None:
    shell = (CSS / "chat_shell.css").read_text("utf-8")
    assert "#tc-shell { --tc-rail-w: 860px; }" in shell
    assert ".tc-rail:not(#tc-welcome) { max-width: var(--tc-rail-w) !important; }" in shell
    assert ".tc-composer-note { display: none !important; }" in shell
    assert "--tc-code-col-ideal: 860px;" in (CSS / "unified_code_mode.css").read_text("utf-8"), "Build's own measure"


def test_the_rails_are_centred_against_the_sidebar_every_mode_now_has() -> None:
    shell = (CSS / "chat_shell.css").read_text("utf-8")
    assert "max(0px, 256px + var(--sidebar-margin, 0px)) / 2 - var(--tc-rail-w, 860px) / 2" in shell


def test_a_sidebar_width_you_set_yourself_is_left_alone() -> None:
    modes = (CSS / "unified_modes.css").read_text("utf-8")
    rule = '#tc-shell[data-surface-mode="code"] .tc-sidebar, #tc-shell .tc-sidebar[style*="width: 280px"]'
    assert rule + " { width: 256px !important; }" in modes
    assert "#tc-shell .tc-sidebar { width: 256px !important; }" not in modes, "that would override a saved width"
