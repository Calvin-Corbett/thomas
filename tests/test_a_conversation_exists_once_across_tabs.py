
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok, open_shell  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

ACTIVE_TITLE = "() => document.querySelector('.bt-tab.is-active .bt-tab-title').textContent"
DOC_COUNT = "() => document.querySelectorAll('iframe.bt-doc').length"
WS_COUNT = "() => document.querySelectorAll('iframe.tc-workspace-frame.bt-frame').length"


@pytest.fixture(scope="module")
def shell():
    with open_shell() as s:
        yield s


def wait_ready(shell, count: int) -> None:
    shell.page.wait_for_function(
        f"() => document.querySelectorAll('iframe.bt-doc.is-ready').length >= {count}", timeout=20000
    )


def test_the_build_button_opens_a_build_document_and_home_stays_in_chat(shell) -> None:
    page = shell.page
    page.click('.tc-mode-button[data-thomas-mode="code"]')
    wait_ready(shell, 1)
    build = shell.docs()[0]
    build.wait_for_function("() => document.getElementById('tc-shell').dataset.surfaceMode === 'code'", timeout=10000)
    assert page.evaluate("() => document.getElementById('tc-shell').dataset.surfaceMode") == "chat"
    assert build.evaluate("() => getComputedStyle(document.getElementById('tc-mode-surface')).display") == "flex"
    page.click(".bt-tab.is-pinned")
    page.click('.tc-mode-button[data-thomas-mode="code"]')
    page.wait_for_timeout(200)
    assert page.evaluate(DOC_COUNT) == 1
    assert page.evaluate(ACTIVE_TITLE) == "Build"
    page.wait_for_timeout(1500)
    stored = page.evaluate("() => localStorage.getItem('thomas.lastSurface') || ''")
    assert '"mode":"code"' not in stored, stored


def test_a_row_clicked_inside_another_tab_focuses_the_tab_that_holds_it(shell) -> None:
    page = shell.page
    page.click(".bt-tab.is-pinned")
    page.click('#tc-chats [data-history-title="Beta"]')
    wait_ready(shell, 2)
    page.click(".bt-tab.is-pinned")
    page.click('#tc-chats [data-history-title="Gamma"]')
    wait_ready(shell, 3)
    gamma = shell.docs()[2]
    gamma.wait_for_function("() => document.getElementById('tc-thread').childElementCount > 0", timeout=20000)
    gamma.fill("#tc-input", "gamma keeps this")
    gamma.click('#tc-chats [data-history-title="Beta"]')
    page.wait_for_timeout(300)
    assert page.evaluate(DOC_COUNT) == 3
    assert page.evaluate(ACTIVE_TITLE) == "Beta"
    assert gamma.evaluate("() => document.getElementById('tc-input').value") == "gamma keeps this"
    beta = shell.docs()[1]
    beta.click('#tc-chats [data-history-title="Gamma"]')
    page.wait_for_timeout(300)
    assert page.evaluate(DOC_COUNT) == 3
    assert page.evaluate(ACTIVE_TITLE) == "Gamma"


def test_settings_opens_one_workspace_tab_from_anywhere(shell) -> None:
    page = shell.page
    page.click(".bt-tab.is-pinned")
    page.click("#tc-settings")
    page.wait_for_timeout(300)
    assert page.evaluate(WS_COUNT) == 1
    assert page.evaluate("() => document.getElementById('tc-direct-frame')") is None
    assert page.evaluate(ACTIVE_TITLE) == "Settings"
    gamma = shell.docs()[2]
    page.click(".bt-tab:nth-child(4)")
    gamma.click("#tc-settings")
    page.wait_for_timeout(300)
    assert page.evaluate(WS_COUNT) == 1
    assert page.evaluate(ACTIVE_TITLE) == "Settings"


def test_a_theme_change_reaches_every_document(shell, tmp_path) -> None:
    page = shell.page
    page.click("#bt-profile")
    page.click("#tc-theme-btn")
    page.click('#tc-theme-options button:has-text("Light")')
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('iframe.bt-doc')).every(f => f.contentDocument.getElementById('tc-shell').dataset.theme === 'light')",
        timeout=5000,
    )
    home_bg = page.evaluate("() => getComputedStyle(document.getElementById('tc-shell')).backgroundColor")
    for doc in shell.docs():
        assert doc.evaluate("() => getComputedStyle(document.getElementById('tc-shell')).backgroundColor") == home_bg
        assert doc.evaluate("() => getComputedStyle(document.getElementById('tc-theme-menu')).display") == "none"
    page.screenshot(path=str(tmp_path / "light.png"))
    assert not shell.errors, shell.errors
