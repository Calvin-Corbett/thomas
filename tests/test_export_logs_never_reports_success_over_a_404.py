"""Export Logs never reports success over a 404.

Verified finding ONE of the owner's 2026-09-01 directive: the button fetched
/api/logs/export, a route registered nowhere, turned the 14-byte 404 body into
a blob, downloaded it as a zip and said Logs exported successfully. The
diagnostics you would attach to a bug report were never collected. Now the
button is disabled at load with a plain title while the route is missing, the
handler refuses anything that is not OK and an archive, and the success toast
appears only after a real archive was handed to the browser. Driven against
``tests/web_fixtures/thomas_chat_fixture.py``, which serves the real settings
page and answers the route the way the server does (404) or the way a real
export would (a zip).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok, serve  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

BUTTON = 'button[onclick="exportLogs()"]'
TOASTS = "() => Array.from(document.querySelectorAll('#toastContainer .toast')).map(t => [t.className, t.textContent.trim().slice(0, 80)])"


def _open_settings(playwright, fixture):
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True).new_page()
    downloads = []
    page.on("download", lambda d: downloads.append(d))
    page.goto(fixture.url + "/settings?embed=1", wait_until="load")
    page.wait_for_function("() => typeof window.exportLogs === 'function'", timeout=10000)
    page.wait_for_timeout(600)
    return browser, page, downloads


def test_the_button_says_so_when_the_route_is_missing_and_never_downloads_a_404() -> None:
    from playwright.sync_api import sync_playwright

    with serve() as fixture, sync_playwright() as p:
        browser, page, downloads = _open_settings(p, fixture)
        page.wait_for_function(f"() => document.querySelector('{BUTTON}').disabled === true", timeout=5000)
        assert "not available" in page.get_attribute(BUTTON, "title").lower()
        page.evaluate("() => window.exportLogs()")
        page.wait_for_timeout(1000)
        toasts = page.evaluate(TOASTS)
        assert any("error" in cls and "Failed to export logs" in text for cls, text in toasts), toasts
        assert not any("success" in cls for cls, _ in toasts), toasts
        assert downloads == []
        browser.close()


def test_a_real_archive_downloads_and_only_then_reports_success() -> None:
    from playwright.sync_api import sync_playwright

    with serve() as fixture, sync_playwright() as p:
        fixture.log_export = "zip"
        browser, page, downloads = _open_settings(p, fixture)
        assert page.evaluate(f"() => document.querySelector('{BUTTON}').disabled") is False
        page.click('.sidebar-nav-item[data-section="advanced"]')  # the button lives in Advanced
        with page.expect_download(timeout=10000) as info:
            page.click(BUTTON)
        download = info.value
        assert download.suggested_filename.endswith(".zip")
        page.wait_for_timeout(500)
        toasts = page.evaluate(TOASTS)
        assert any("success" in cls for cls, _ in toasts), toasts
        assert not any("error" in cls for cls, _ in toasts), toasts
        browser.close()
