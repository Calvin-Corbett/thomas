"""The home tab keeps its own conversation, and every tab keeps its own controls.

Findings from the adversarial review of the tab shell (2026-09-01), each one
reproduced in a browser before it was fixed: a conversation born on a blank
home was never learned, so its own row opened a duplicate tab; New chat on a
busy tab opened a copy of the current conversation, because the child restored
the reload keys; a home carried into Build could never come back to Chat;
reload on home destroyed every other tab; the nav-row model pill governed home
while a document tab sent with its own model; and the sidebar popped open or
closed on every switch. Driven against ``tests/web_fixtures/thomas_chat_fixture.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok, open_shell  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

ACTIVE_TITLE = "() => document.querySelector('.bt-tab.is-active .bt-tab-title').textContent"
HOME_TITLE = "() => document.querySelector('.bt-tab.is-pinned .bt-tab-title').textContent"
DOC_COUNT = "() => document.querySelectorAll('iframe.bt-doc').length"
MARGIN = "() => document.getElementById('tc-shell').style.getPropertyValue('--sidebar-margin').trim()"
PILL = "() => getComputedStyle(document.querySelector('[data-model-switch]')).display"


@pytest.fixture(scope="module")
def shell():
    with open_shell() as s:
        yield s


def wait_ready(shell, count: int) -> None:
    shell.page.wait_for_function(
        f"() => document.querySelectorAll('iframe.bt-doc.is-ready').length >= {count}", timeout=20000
    )


def test_a_conversation_born_on_home_is_learned_and_its_row_focuses_home(shell) -> None:
    page = shell.page
    page.click("#tc-newchat")
    page.wait_for_timeout(300)
    assert page.evaluate(HOME_TITLE) == "Chat"
    page.fill("#tc-input", "fresh one on home")
    page.press("#tc-input", "Enter")
    page.wait_for_function(
        "() => !document.querySelector('.tc-mode-button[data-thomas-mode=chat]').hasAttribute('data-running')"
        " && document.querySelectorAll('#tc-thread .tc-bubble').length >= 2",
        timeout=20000,
    )
    page.wait_for_function("() => document.querySelector('.bt-tab.is-pinned .bt-tab-title').textContent !== 'Chat'", timeout=5000)
    assert page.evaluate(HOME_TITLE) == "fresh one on home"
    page.click('#tc-chats [data-history-title="fresh one on home"]')
    page.wait_for_timeout(800)
    assert page.evaluate(DOC_COUNT) == 0
    assert page.evaluate("() => document.querySelector('.bt-tab.is-pinned').classList.contains('is-active')") is True
    assert page.evaluate("() => localStorage.getItem('thomas_last_chat')") == "conv-1"


def test_new_chat_on_a_busy_home_opens_a_blank_tab_not_a_copy(shell) -> None:
    page = shell.page
    page.fill("#tc-input", "second turn, keep me busy")
    page.press("#tc-input", "Enter")
    page.wait_for_timeout(300)
    page.click("#tc-newchat")
    wait_ready(shell, 1)
    fresh = shell.docs()[0]
    fresh.wait_for_function("() => document.readyState === 'complete'", timeout=10000)
    page.wait_for_timeout(1200)
    assert fresh.evaluate("() => document.getElementById('tc-thread').childElementCount") == 0
    assert page.evaluate(ACTIVE_TITLE) == "Chat"
    assert page.evaluate("() => document.getElementById('tc-thread').childElementCount") >= 2
    page.wait_for_function(
        "() => !document.querySelector('.tc-mode-button[data-thomas-mode=chat]').hasAttribute('data-running')", timeout=20000
    )


def test_the_home_pill_hides_off_home_and_a_document_shows_its_own(shell) -> None:
    page = shell.page
    doc = shell.docs()[0]
    page.click(".bt-tab:nth-child(2)")
    page.wait_for_timeout(200)
    assert page.evaluate(PILL) == "none"
    assert doc.evaluate(PILL) != "none"
    assert doc.evaluate("() => getComputedStyle(document.querySelector('main > header')).display") != "none"
    page.click(".bt-tab.is-pinned")
    page.wait_for_timeout(200)
    assert page.evaluate(PILL) != "none"


def test_the_sidebar_folds_in_every_document_together(shell) -> None:
    page = shell.page
    doc = shell.docs()[0]
    page.click("#tc-sidebar-toggle")
    page.wait_for_timeout(400)
    assert page.evaluate(MARGIN) == "-280px"
    assert doc.evaluate(MARGIN) == "-280px"
    page.click("#tc-sidebar-toggle")
    page.wait_for_timeout(400)
    assert page.evaluate(MARGIN) in ("0px", "0", "")
    assert doc.evaluate(MARGIN) in ("0px", "0", "")


def test_reload_on_home_refuses_to_close_the_other_tabs(shell) -> None:
    page = shell.page
    page.click(".bt-tab.is-pinned")
    before = page.evaluate(DOC_COUNT)
    page.click("#bt-reload")
    page.wait_for_timeout(500)
    assert page.evaluate(DOC_COUNT) == before
    notices = "() => Array.from(document.querySelectorAll('[role=status]')).map(e => e.textContent).join(' | ')"
    assert "close every other tab" in page.evaluate(notices)


def test_chat_brings_a_home_carried_into_build_back(shell) -> None:
    page = shell.page
    page.click(".bt-tab.is-pinned")
    page.evaluate("() => window.ThomasUnifiedModes.setMode('code')")
    page.wait_for_function("() => document.getElementById('tc-shell').dataset.surfaceMode === 'code'", timeout=5000)
    page.wait_for_timeout(200)
    assert page.evaluate(HOME_TITLE) == "Build"
    docs_before = page.evaluate(DOC_COUNT)
    page.click('.tc-mode-button[data-thomas-mode="chat"]')
    page.wait_for_function("() => document.getElementById('tc-shell').dataset.surfaceMode === 'chat'", timeout=5000)
    assert page.evaluate(DOC_COUNT) == docs_before
    assert page.evaluate("() => document.querySelector('.bt-tab.is-pinned').classList.contains('is-active')") is True
    assert not shell.errors, shell.errors
