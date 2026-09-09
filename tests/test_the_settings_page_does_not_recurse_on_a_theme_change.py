"""The settings page does not recurse on a theme change.

Found while fixing Export Logs: the settings page listens for the theme
engine's thomas:themechange event and answers by calling the engine's
applier, which dispatches the same event, so every theme change after boot
ended in RangeError: Maximum call stack size exceeded (workspace_shell.js
applyTheme and settings.script01.js applyChatTheme, on every server). The page
now records the theme before it calls the engine and ignores an event for a
theme already recorded. Driven against the real settings page served by
``tests/web_fixtures/thomas_chat_fixture.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok, serve  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")


def test_a_theme_change_on_the_settings_page_applies_once_and_throws_nothing() -> None:
    from playwright.sync_api import sync_playwright

    with serve() as fixture, sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(fixture.url + "/settings?embed=1", wait_until="load")
        page.wait_for_function("() => typeof window.exportLogs === 'function'", timeout=10000)
        page.wait_for_timeout(500)
        assert errors == [], errors
        calls = page.evaluate(
            "() => { let n = 0; const orig = window.ThomasWorkspaceShell.applyTheme;"
            " window.ThomasWorkspaceShell.applyTheme = (t, o) => { n += 1; return orig(t, o); };"
            " window.ThomasWorkspaceShell.applyTheme('light'); return n; }"
        )
        page.wait_for_timeout(300)
        assert errors == [], errors
        assert calls <= 2, f"the engine was re-entered {calls} times for one change"
        assert page.evaluate("() => document.documentElement.dataset.theme") == "light"
        assert page.evaluate("() => document.body.dataset.theme") == "light"
        assert page.evaluate("() => document.getElementById('theme').value") == "light"
        browser.close()
