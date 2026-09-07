"""The browser chrome is on unless you turn it off.

Owner charter, 2026-09-01: tabs need no Electron. The tab shell is the web
UI's default frame in a plain browser. It stays off only when asked: ?browser=0
on the address, or thomas_browser_shell=off in storage (which the profile
menu's Classic layout writes). ?browser=1 always wins. It never attaches inside
an embedded document, never in the desktop app (whose preload attaches the same
chain), never twice, and never on a page without the chat shell. Driven through
the real module in a vm context by ``tests/web_node/workspace_shell_gate.mjs``,
plus two source pins for the guards that live in other files.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SHELL_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "workspace_shell.js"
BROWSER_SHELL_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "browser_shell.js"
PRELOAD_JS = REPO_ROOT / "desktop" / "preload.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "workspace_shell_gate.mjs"


@pytest.fixture(scope="module")
def report() -> dict[str, dict[str, object]]:
    result = subprocess.run(
        ["node", str(HARNESS), str(SHELL_JS)],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_chrome_attaches_by_default_in_a_plain_browser(report) -> None:
    assert report["default_on"]["attach"] is True
    assert report["other_query"]["attach"] is True


def test_the_address_and_the_stored_choice_can_turn_it_off(report) -> None:
    assert report["query_off"]["attach"] is False
    assert report["stored_off"]["attach"] is False


def test_the_address_wins_over_the_stored_choice(report) -> None:
    assert report["query_on_beats_stored_off"]["attach"] is True


def test_it_never_attaches_where_another_chrome_already_lives(report) -> None:
    assert report["desktop"]["attach"] is False
    assert report["embedded"]["attach"] is False
    assert report["attached"]["attach"] is False
    assert report["no_shell"]["attach"] is False


def test_the_desktop_preload_refuses_to_attach_twice() -> None:
    src = PRELOAD_JS.read_text(encoding="utf-8")
    guard = src.index('getElementById("bt-titlebar")')
    chain = src.index("browser_shell_panel.js")
    assert guard < chain, "the already-attached guard must run before the chain loads"


def test_the_profile_menu_offers_the_classic_layout_as_the_way_out() -> None:
    src = BROWSER_SHELL_JS.read_text(encoding="utf-8")
    assert "Classic layout" in src
    assert '"thomas_browser_shell", "off"' in src
