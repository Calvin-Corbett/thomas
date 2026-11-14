"""What the desktop row's words say Settings does with the row off, read from a real window.

These are the words of ``thomas.server.rows.desktop`` for the routes of ``thomas.server.routes.desktop_aiohttp``. The
Isolated Desktop Mode section is under Advanced in Settings, and it is drawn by ``settings.isolated-desktop.js``.

Two buttons on it launch real programs when the row is on. The server this starts is given a ``Popen`` that refuses them,
the same one ``tests/test_turning_desktop_off_touches_only_its_routes.py`` uses, and they are pressed only with the row
off, where the routes they call are gone.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.row_page_fixture import _SERVE, serving
from tests.row_proof_fixture import ROWS
from tests.test_turning_desktop_off_touches_only_its_routes import THE_LAUNCHES
from tests.web_fixtures.thomas_chat_fixture import browser_ok

WINDOW = {"width": 1366, "height": 768}
WORDS = next(row for row in ROWS if row.id == "desktop").config["words"]
STATUS = "/api/onboarding/desktop/status"
# Put on the settings page before anything is pressed, so each message it shows is kept for the test to read.
KEEP_TOASTS = (
    "() => { window.__toasts = []; const show = window.showToast;"
    " window.showToast = (m, t) => { window.__toasts.push(m); return show && show(m, t); }; }"
)
SECTION = """() => ({
    badge: document.getElementById('isolatedDesktopStatusText').innerText,
    switch_on: document.getElementById('isolatedDesktopEnabled').classList.contains('on'),
    install_greyed: document.getElementById('installHostServiceButton').disabled,
    viewer_greyed: document.getElementById('openViewerButton').disabled,
})"""


def _settings(page: Any, base: str) -> Any:
    """Open Settings from the sidebar, the way you would, and its Advanced section. Returns the frame it is in."""
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector(".bt-tab")
    page.locator("button:has-text('Settings')").nth(1).click()
    page.wait_for_selector("iframe[src*='/settings']", state="attached")
    for _ in range(100):  # the frame has the address a moment after the page has the frame
        found = [f for f in page.frames if "/settings" in f.url]
        if found:
            break
        page.wait_for_timeout(100)
    frame = found[0]
    frame.wait_for_selector("#isolatedDesktopStatusText", state="attached")
    page.wait_for_timeout(1500)
    frame.evaluate(KEEP_TOASTS)
    frame.get_by_text("Advanced", exact=True).first.click(force=True)
    page.wait_for_timeout(500)
    return frame


def _press(page: Any, frame: Any, button: str, wait: int = 2000) -> list[str]:
    frame.evaluate("() => { window.__toasts.length = 0 }")
    frame.locator(button).click(force=True)
    page.wait_for_timeout(wait)
    return frame.evaluate("() => window.__toasts.slice()")


def _walk(base: str, browser: Any) -> dict[str, Any]:
    """Set up with the row on, then turned off and looked at, then on again."""
    seen: dict[str, Any] = {}
    context = browser.new_context(viewport=WINDOW)
    asked: Counter[str] = Counter()
    context.on("request", lambda request: asked.update([urlsplit(request.url).path]))

    def press(state: str) -> None:
        assert context.request.post(f"{base}/api/plugins/thomas/desktop/{state}", data={}).status == 200

    def posture() -> dict[str, Any]:
        found = context.request.get(f"{base}{STATUS}").json()["isolated_desktop"]
        return {key: found[key] for key in ("enabled", "installation_state", "trust_mode")}

    def mission_and_setup() -> tuple[Any, Any]:
        mission = context.request.get(f"{base}/api/mission/control").json().get("desktop_operator")
        setup = context.request.get(f"{base}/api/setup/bootstrap").json().get("isolated_desktop")
        return mission, setup

    # Set up with the row on, so what is read back later is something that was really there.
    assert context.request.post(f"{base}/api/onboarding/desktop/opt-in", data={"enabled": True}).status == 200
    seen["set_up"] = posture()
    seen["mission_and_setup_on"] = mission_and_setup()
    page = context.new_page()
    page.set_default_timeout(60_000)
    frame = _settings(page, base)
    seen["section_on"] = frame.evaluate(SECTION)

    press("off")
    page.wait_for_timeout(3000)
    seen["open_page_after_off"] = frame.evaluate(SECTION)
    seen["mission_and_setup_off"] = mission_and_setup()
    page.close()

    page = context.new_page()
    page.set_default_timeout(60_000)
    asked.clear()
    frame = _settings(page, base)
    seen["section_off"] = frame.evaluate(SECTION)
    seen["routes_gone"] = [
        context.request.post(f"{base}/api/onboarding/desktop/{leaf}", data={}).status
        for leaf in ("install", "open-viewer")
    ]
    # Pressed only now, with both routes known to be gone, because on they launch programs.
    seen["refresh"] = _press(page, frame, "#refreshDesktopStatusButton")
    frame.evaluate("() => { const s = document.getElementById('isolatedDesktopTrustMode'); s.value = 'always_allow'; }")
    seen["save"] = _press(page, frame, "#saveIsolatedDesktopButton", 3000)
    seen["install"] = _press(page, frame, "#installHostServiceButton")
    seen["viewer"] = _press(page, frame, "#openViewerButton")
    asked.clear()
    page.wait_for_timeout(10_000)
    seen["asked_in_ten_seconds"] = sum(count for path, count in asked.items() if path.startswith("/api/onboarding"))
    page.close()

    press("on")
    seen["after_on"] = posture()
    page = context.new_page()
    page.set_default_timeout(60_000)
    frame = _settings(page, base)
    seen["section_back_on"] = frame.evaluate(SECTION)
    return seen


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One walk through the real page, for the tests below to read."""
    # With THOMAS_REQUIRE_BROWSER_TESTS=1 this raises, so a run that must have a browser cannot skip.
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    with (
        serving(tmp_path_factory.mktemp("desktop-page"), script=THE_LAUNCHES + _SERVE) as base,
        sync_playwright() as playwright,
    ):
        return _walk(base, playwright.chromium.launch(headless=True))


def test_it_was_really_set_up_before_it_was_turned_off(walked: dict[str, Any]) -> None:
    assert walked["set_up"] == {
        "enabled": True,
        "installation_state": "host_service_not_installed",
        "trust_mode": "ask_every_time",
    }
    assert walked["section_on"]["badge"] == "host service not installed"
    assert walked["section_on"]["install_greyed"] is False


def test_the_section_stays_and_reads_not_enabled_after_a_reload_whatever_you_set(walked: dict[str, Any]) -> None:
    assert walked["section_off"] == {
        "badge": "Not Enabled",
        "switch_on": False,
        "install_greyed": False,
        "viewer_greyed": False,
    }
    assert "Not Enabled" in WORDS["off_means"]
    assert "neither is greyed out" in WORDS["off_means"]


def test_each_press_shows_the_red_message_the_words_give_and_save_says_saved(walked: dict[str, Any]) -> None:
    assert walked["routes_gone"] == [404, 404]
    assert walked["refresh"] == ["Failed to load isolated desktop status"]
    assert walked["save"] == ["Failed to load isolated desktop status", "Isolated desktop settings saved"]
    assert walked["install"] == ["Failed to launch isolated desktop install"]
    assert walked["viewer"] == ["Failed to open isolated desktop viewer"]
    for message in (*walked["save"], *walked["install"], *walked["viewer"]):
        assert message in WORDS["off_means"]


def test_what_was_saved_with_the_row_off_was_not_saved_and_what_was_there_stays(walked: dict[str, Any]) -> None:
    assert walked["after_on"] == walked["set_up"]
    assert walked["section_back_on"]["badge"] == "host service not installed"


def test_nothing_asks_again_and_again(walked: dict[str, Any]) -> None:
    assert walked["asked_in_ten_seconds"] == 0


def test_a_page_already_open_keeps_what_it_last_showed(walked: dict[str, Any]) -> None:
    assert walked["open_page_after_off"] == walked["section_on"]


def test_mission_control_and_easy_setup_stop_reporting_it_and_report_again_when_on(walked: dict[str, Any]) -> None:
    mission, setup = walked["mission_and_setup_on"]
    assert mission["service_id"] == "desktop.operator"
    assert setup["installation_state"] == "host_service_not_installed"
    assert walked["mission_and_setup_off"] == ({}, {"installation_state": "not_enabled"})
