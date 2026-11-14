"""The settings page keeps the exact theme name Thomas saved, not just light or dark.

Proves thomas/server/web/settings.script01.js (toUiTheme and buildLegacySettings). The preferences API knows two themes,
so every settings page saves the pair (appearance.theme light or dark, legacy_settings.theme the exact name such as
nebula) as it starts. A page opened on a device with no stored theme read only the first half, so Settings turned a
Nebula copy of Thomas into plain dark a moment after it opened, depending on which request landed first (found 2026-11-03
when tests/test_every_document_applies_the_overlay.py failed one run in three). Driven against the real settings page
served by ``tests/web_fixtures/thomas_chat_fixture.py`` with the preferences answer replaced and no stored theme.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok, serve  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")


def _opened_with(saved_api: str, saved_exact: str | None) -> tuple[str, str]:
    """Open Settings in a browser with nothing stored; return the theme on the page and on its picker."""
    from playwright.sync_api import sync_playwright

    legacy = {"theme": saved_exact} if saved_exact else {}
    body = json.dumps({"appearance": {"theme": saved_api}, "thomads": {"legacy_settings": legacy}})

    def answer(route) -> None:
        if route.request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=body)
        else:
            route.continue_()

    with serve() as fixture, sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        page.route("**/api/preferences", answer)
        page.goto(fixture.url + "/settings?embed=1", wait_until="load")
        page.wait_for_function("() => typeof window.exportLogs === 'function'", timeout=10000)
        page.wait_for_timeout(700)
        shown = page.evaluate("() => document.documentElement.dataset.theme")
        picked = page.evaluate("() => document.getElementById('theme').value")
        browser.close()
    return shown, picked


@pytest.mark.parametrize(
    ("saved_api", "saved_exact", "expected"),
    [
        ("dark", "nebula", "nebula"),
        # Two looks only (2026-11-10: "get rid of the theme selector, just make it dark or light"): an older choice opens as the nearer
        # of the two, and Dark is stored under the old default's name, "nebula".
        ("light", "sandstone", "light"),
        ("dark", None, "nebula"),
        ("light", "nebula", "light"),
    ],
)
def test_settings_opens_in_the_theme_that_was_saved(saved_api, saved_exact, expected) -> None:
    shown, picked = _opened_with(saved_api, saved_exact)
    assert shown == expected, (saved_api, saved_exact, shown)
    assert picked == expected, (saved_api, saved_exact, picked)
