"""What the onboarding row's words say first-run setup does with the row off, read from a real window.

These are the words of ``thomas.server.rows.onboarding`` for the three routes of ``thomas.server.routes.onboarding_aiohttp``.
Easy Setup is part of the older full page, so it lives in ``easy_setup_connection_flow.js`` and
``006_easy_setup_onboarding_04.js``. The walk runs against the stand-in for Ollama that the setup row's walk uses, so it
says the same on any machine and pulls nothing. It goes from a new install to the end of setup with the row off, then asks
the Tools Console for the readings.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROWS
from tests.test_turning_setup_off_what_easy_setup_shows import _SERVE, OPEN, WINDOW
from tests.web_fixtures.thomas_chat_fixture import browser_ok

WORDS = next(row for row in ROWS if row.id == "onboarding").config["words"]
NOTES = "/api/onboarding/telemetry"
READING = "/api/onboarding/outcomes/gate"


def _walk(base: str, browser: Any) -> dict[str, Any]:
    """A new install with the row off, as you would meet it, to the end of setup and then the Tools Console."""
    seen: dict[str, Any] = {}
    context = browser.new_context(viewport=WINDOW)
    asked: Counter[str] = Counter()
    answered: Counter[tuple[str, int]] = Counter()
    context.on("request", lambda request: asked.update([urlsplit(request.url).path]))
    context.on("response", lambda answer: answered.update([(urlsplit(answer.url).path, answer.status)]))
    assert context.request.post(f"{base}/api/plugins/thomas/onboarding/off", data={}).status == 200

    page = context.new_page()
    page.set_default_timeout(60_000)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector(".bt-tab")
    page.wait_for_timeout(3000)
    seen["chat_opens"] = bool(page.evaluate(OPEN))
    page.click("button:has-text('Marketplace')")
    frame = page.frame_locator("iframe[src*='classic']")
    frame.locator("#easySetupModal.active").wait_for(state="visible")
    seen["opens_over_a_page"] = True

    page.goto(f"{base}/classic", wait_until="domcontentloaded")
    page.wait_for_function(OPEN)
    page.click("#easySetupDismissBtn")
    page.wait_for_function("() => !document.getElementById('easySetupModal').classList.contains('active')")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    seen["back_after_skip"] = page.evaluate(OPEN)

    page.evaluate("() => openEasySetup({ source: 'slash', force: true, restart: true })")
    page.wait_for_function(OPEN)
    page.click("#easySetupPathGrid [data-path='local']")
    page.click("#easySetupNextBtn")
    page.click("#easySetupTestConnectionBtn")
    page.wait_for_function(
        "() => /Verified|failed/.test(document.getElementById('easySetupConnectionStatus').innerText)", timeout=180_000
    )
    seen["tested"] = page.locator("#easySetupConnectionStatus").inner_text().strip()
    for _ in range(4):
        page.click("#easySetupNextBtn")
        page.wait_for_timeout(700)
    page.get_by_text("Skip intake").first.click(force=True)
    page.get_by_text("Finish setup with defaults").first.click(force=True)
    page.wait_for_function(
        "async () => (await (await fetch('/api/preferences')).json()).onboarding?.setup_completed === true"
    )
    seen["finished"] = True
    asked.clear()
    page.wait_for_timeout(10_000)
    seen["asked_in_ten_seconds"] = sum(count for path, count in asked.items() if path.startswith("/api/onboarding"))
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    seen["back_after_finishing"] = page.evaluate(OPEN)
    seen["notes_refused"] = answered[(NOTES, 404)]
    seen["notes_taken"] = answered[(NOTES, 200)]

    asked.clear()
    page.evaluate(
        "() => { document.getElementById('debugDock'); document.getElementById('debugDockToggleBtn').click(); }"
    )
    page.wait_for_timeout(1000)
    page.evaluate("() => refreshDebugLiveData({ force: true, reason: 'manual' })")
    page.wait_for_timeout(4000)
    seen["reading_asked"] = asked[READING]
    seen["panel_off"] = page.evaluate("() => [debugOnboardingGateStatus.innerText, debugOnboardingGateList.innerText]")
    assert context.request.post(f"{base}/api/plugins/thomas/onboarding/on", data={}).status == 200
    page.evaluate("() => refreshDebugLiveData({ force: true, reason: 'manual' })")
    page.wait_for_function("() => /Gate warning|Gate failed|passing/.test(debugOnboardingGateStatus.innerText)")
    seen["panel_on"] = page.evaluate("() => debugOnboardingGateStatus.innerText")
    asked.clear()
    page.wait_for_timeout(5000)
    seen["asked_when_idle_on"] = sum(count for path, count in asked.items() if path.startswith("/api/onboarding"))
    return seen


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One walk through the real page, for the tests below to read."""
    # With THOMAS_REQUIRE_BROWSER_TESTS=1 this raises, so a run that must have a browser cannot skip.
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    with serving(tmp_path_factory.mktemp("onboarding-page"), script=_SERVE) as base, sync_playwright() as playwright:
        return _walk(base, playwright.chromium.launch(headless=True))


def test_a_new_install_still_opens_easy_setup_and_it_can_be_skipped_for_good(walked: dict[str, Any]) -> None:
    assert walked["opens_over_a_page"] is True
    assert walked["back_after_skip"] is False
    assert "Skip for now" in WORDS["off_means"]


def test_the_default_page_does_not_open_easy_setup_and_the_words_do_not_say_it_does(walked: dict[str, Any]) -> None:
    # Easy Setup is on the older full page, which the pages named below show and /classic is. Chat is not one of them.
    assert walked["chat_opens"] is False
    said = WORDS["off_means"]
    assert "A new install still opens Easy Setup, and" not in said
    assert "Chat" in said and "older full page" in said
    for page in ("Virtual Office", "Canvas", "Channels", "Token Economy", "Marketplace"):
        assert page in said


def test_setup_can_be_finished_with_the_row_off_and_does_not_come_back(walked: dict[str, Any]) -> None:
    assert walked["tested"].startswith("Local profile")
    assert walked["finished"] is True
    assert walked["back_after_finishing"] is False


def test_the_notes_go_unanswered_and_nothing_asks_again_and_again(walked: dict[str, Any]) -> None:
    assert walked["notes_refused"] >= 6, "the page sent no notes, so this proves nothing about them"
    assert walked["notes_taken"] == 0
    assert walked["asked_in_ten_seconds"] == 0


def test_the_tools_console_says_nothing_has_loaded_and_not_why(walked: dict[str, Any]) -> None:
    assert walked["reading_asked"] == 1
    assert walked["panel_off"] == [
        "Use Refresh to fetch onboarding diagnostics.",
        "No onboarding diagnostics loaded yet.",
    ]
    assert "No onboarding diagnostics loaded yet" in WORDS["off_means"]


def test_turned_back_on_the_console_has_a_reading_and_nothing_asks_by_itself(walked: dict[str, Any]) -> None:
    assert walked["panel_on"].startswith("Gate warning")
    assert walked["asked_when_idle_on"] == 0
