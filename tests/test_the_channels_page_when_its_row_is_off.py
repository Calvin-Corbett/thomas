"""The Channels page with the Discord row off, read from a real window on a real server: it asks twice and then waits.

With the row off every ask for the Discord channel fails, and the page used to answer a failed ask by redrawing, which
asked again at once: about 20 asks a second for as long as the page stayed open. It now waits 75 seconds after a failed
ask before it asks by itself, and anything you press asks at once.

The page's code is ``036_workbench_editors_08.js`` and ``038_module_rendering_dispatch_01.js``, and they call
``thomas.server.routes.discord_channels_aiohttp``, which is the row ``thomas.server.rows.discord``. The words of that row
say what the card shows with it off, and this reads the card.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.row_page_fixture import serving
from tests.web_fixtures.thomas_chat_fixture import browser_ok

CARD = "[data-ui-id='channels.primary.discord']"
TEN_SECONDS = 10_000
LOOPING = 20


def _opened(page: Any, base: str) -> None:
    page.goto(f"{base}/classic?nav=channels", wait_until="domcontentloaded")
    page.wait_for_selector(CARD, timeout=90_000)
    page.evaluate(
        "() => ['easySetupModal', 'easySetupBackdrop'].forEach((id) => document.getElementById(id)?.remove())"
    )


def _walk(base: str, browser: Any) -> dict[str, Any]:
    context = browser.new_context(viewport={"width": 1500, "height": 950})
    asked: list[str] = []
    context.on("request", lambda r: asked.append(r.method + " " + r.url) if "/api/channels/discord" in r.url else None)
    page = context.new_page()
    page.set_default_timeout(60_000)
    seen: dict[str, Any] = {}
    page.goto(base, wait_until="domcontentloaded")
    page.evaluate("async () => (await fetch('/api/plugins/thomas/discord/off', { method: 'POST' })).status")
    asked.clear()
    _opened(page, base)
    page.wait_for_timeout(TEN_SECONDS)
    seen["asks_in_ten_seconds"] = len(asked)
    seen["card"] = " ".join(page.locator(CARD).inner_text().split())
    seen["error_line"] = page.get_by_text("404: Not Found", exact=True).locator("visible=true").count()
    before = len(asked)
    page.get_by_role("button", name="Refresh").first.click()
    page.wait_for_timeout(3000)
    seen["asks_for_one_press"] = len(asked) - before
    page.get_by_role("button", name="Open controls").first.click()
    page.get_by_role("button", name="Start Bridge").first.wait_for(state="visible")
    before = len(asked)
    page.get_by_role("button", name="Start Bridge").first.click()
    page.wait_for_timeout(3000)
    seen["start_asked"] = [line.split(base)[1] for line in asked[before:]]
    context.close()
    return seen


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    folder: Path = tmp_path_factory.mktemp("channels-page")
    with serving(folder) as base, sync_playwright() as playwright:
        return _walk(base, playwright.chromium.launch(headless=True))


def test_the_page_asks_for_the_channel_once_and_then_waits(seen: dict[str, Any]) -> None:
    assert 2 <= seen["asks_in_ten_seconds"] < LOOPING, seen


def test_the_card_reads_off_with_a_404_line_where_a_window_shows_it(seen: dict[str, Any]) -> None:
    assert "Off channel" in seen["card"] and "NOT CONFIGURED" in seen["card"], seen["card"]
    assert seen["error_line"] == 1


def test_a_press_asks_at_once_and_a_button_asks_only_for_what_it_does(seen: dict[str, Any]) -> None:
    assert seen["asks_for_one_press"] == 2
    assert seen["start_asked"] == ["/api/channels/discord/start"]
