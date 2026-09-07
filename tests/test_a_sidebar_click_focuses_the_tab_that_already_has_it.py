"""A sidebar row opens a tab the way Chrome opens one, and a conversation exists once.

Calvin's direction (2026-08-25): when I click on the left it actually opens up a
tab up top like Chrome, and a conversation exists once. So a row whose
conversation is already held by a tab focuses that tab; a row clicked on a
blank, idle surface navigates that surface in place, the way Chrome's new-tab
page does; anything else opens a new tab. Ctrl-click and middle-click always
open one. These are pure decisions, so they are driven through the real module
in a vm context by ``tests/web_node/browser_shell_docs_policy.mjs``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "browser_shell_docs_policy.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "browser_shell_docs_policy.mjs"


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    result = subprocess.run(
        ["node", str(HARNESS), str(POLICY_JS)],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_row_whose_conversation_a_tab_already_holds_focuses_that_tab(report) -> None:
    assert report["row_held_by_home"] == "focus:1"
    assert report["row_held_by_doc"] == "focus:2"


def test_a_row_on_a_blank_idle_surface_navigates_that_surface_in_place(report) -> None:
    assert report["row_on_blank_surface"] == "adopt"


def test_a_modifier_click_always_opens_a_new_tab(report) -> None:
    assert report["row_on_blank_with_ctrl"] == "open"
    assert report["row_on_blank_with_middle"] == "open"


def test_a_draft_or_a_running_turn_is_never_navigated_away_from(report) -> None:
    assert report["row_on_drafted_surface"] == "open"
    assert report["row_on_busy_surface"] == "open"
    assert report["blank_idle_with_content"] is False
    assert report["blank_idle_when_holding"] is False
    assert report["row_on_holding_surface"] == "open"


def test_a_row_of_another_mode_never_adopts_this_surface(report) -> None:
    assert report["row_on_other_mode_surface"] == "open"


def test_a_mode_button_focuses_the_newest_tab_of_that_mode_or_opens_one(report) -> None:
    assert report["mode_click_home_mode"] == 1
    assert report["mode_click_newest_doc"] == 4
    assert report["mode_click_no_doc"] == "open"


def test_new_chat_reuses_a_blank_surface_and_spares_a_busy_one(report) -> None:
    assert report["new_chat_on_blank"] == "adopt"
    assert report["new_chat_on_drafted"] == "open"
    assert report["new_chat_on_busy_keeps_mode"] == "code"


def test_a_tab_document_address_never_attaches_the_chrome_and_only_code_deep_links(report) -> None:
    assert report["url_chat"] == "/?embed=1&browser=0"
    assert report["url_code"] == "/?embed=1&browser=0&forge_code=c%2F1"
    assert report["url_work"] == "/?embed=1&browser=0"
