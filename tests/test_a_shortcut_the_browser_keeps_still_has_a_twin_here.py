"""A shortcut the browser keeps for itself still has a twin here.

In a plain browser tab Chrome and Edge keep Ctrl+T, Ctrl+W, Ctrl+Tab and
Ctrl+Shift+Tab for their own tabs; the page never sees them. The strip keeps
those bindings for the desktop app and adds ones the browser leaves alone:
Alt+1..9, Alt+PageDown and Alt+PageUp. No Ctrl+Shift combination is bound: the
layout editor treats a Ctrl+Shift press-and-release as the chord that toggles
Redesign mode, so a swallowed Ctrl+Shift+] armed the editor inside every tab
document and its click layer ate every click there (found in a browser on
2026-09-01). A binding whose action does nothing must not swallow the
browser's own default, and the listener must be installable on a tab
document, because a keydown inside an iframe never reaches the parent. Driven
through the real module in a vm context by ``tests/web_node/browser_shell_keys.mjs``;
what a headless browser delivers is evidence about the handler, not proof of
real-browser delivery.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "browser_shell_keys.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "browser_shell_keys.mjs"


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    result = subprocess.run(
        ["node", str(HARNESS), str(KEYS_JS)],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_chrome_bindings_stay_as_they_are(report) -> None:
    assert report["ctrl_2"] == ["select-tab", 2]
    assert report["ctrl_9"] == ["select-tab", 9]
    assert report["ctrl_tab"] == ["next-tab"]
    assert report["ctrl_t"] == ["new-tab"]


def test_every_reserved_binding_has_a_twin_the_browser_leaves_alone(report) -> None:
    assert report["alt_3"] == ["select-tab", 3]
    assert report["alt_pagedown"] == ["next-tab"]
    assert report["alt_pageup"] == ["prev-tab"]


def test_ordinary_typing_and_altgraph_layouts_are_never_disturbed(report) -> None:
    assert report["plain_3"] is None
    assert report["ctrl_shift_3"] is None
    assert report["alt_3_altgraph"] is None


def test_no_ctrl_shift_combination_is_bound_because_the_layout_editor_owns_that_chord(report) -> None:
    assert report["ctrl_shift_bracket_right"] is None
    assert report["ctrl_shift_bracket_left"] is None
    assert report["ctrl_shift_e"] is None


def test_a_binding_whose_action_does_nothing_keeps_the_browser_default(report) -> None:
    assert report["alt_left_prevented"] is False
    assert report["ctrl_2_prevented"] is True
    assert "back" in report["calls"]


def test_the_listener_can_be_installed_on_a_tab_document(report) -> None:
    assert report["attached_keydown"] is True


def test_the_shortcut_table_is_honest_about_what_a_plain_browser_keeps(report) -> None:
    table = dict(report["bindings"])
    assert table["Alt+1..9"] is True
    assert table["Alt+PageDown / Alt+PageUp"] is True
    assert table["Ctrl+Tab / Ctrl+Shift+Tab"] is False
    assert table["Ctrl+T / Ctrl+W"] is False
    assert not any("Ctrl+Shift+]" in k for k in table)
