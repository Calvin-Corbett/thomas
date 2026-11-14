"""The Marketplace page with its row off, in a real browser on a real server, and when its list cannot be had at all.

The row is ``thomas.server.rows.catalog``, and its routes are in ``thomas.server.routes.marketplace_catalog_aiohttp``,
``thomas.server.routes.plugin_hosting`` and ``thomas.server.routes.standalone_app_aiohttp``. The page's code is
``036_workbench_editors_08.js``, ``025_module_system_command_center_01.js`` and ``marketplace_kernel.js``. Those names are
how a check finds this file when one of them changes. ``tests/marketplace_page_fixture.py`` walks the page with the row
on, then off with two pages open, then each reloaded, then on again, and the tests here read what it saw. The row's
words say what you see, and reading a file or finding a word in the page says nothing of that: it can sit where no
window shows it. Each sentence of the words is listed in ``tests/test_the_plugins_page_speaks_plainly.py`` with the
tests that show it.

The routes, the fresh-process proofs and the access guard are in
``tests/test_turning_catalog_off_touches_only_its_routes.py``.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.marketplace_page_fixture import (
    CARD,
    HEAD,
    HEAD_OFF,
    PAGE_FRAME,
    REFRESH,
    SIDEBAR_BUTTON,
    SYNC,
    TYPED,
    UNAVAILABLE,
    WAITS_THROUGH,
    WINDOW,
    open_marketplace,
    walk,
    words,
)
from tests.row_page_fixture import serving
from tests.web_fixtures.thomas_chat_fixture import browser_ok

TAB_X = ".bt-tab:has-text('Marketplace') .bt-tab-x"
# Seconds. A click or a reload here takes a fraction of one, and a frozen window never answers at all.
FROZEN_AFTER = 20


def _after_a_failure_with_the_row_on(base: str, browser: Any, failure: Callable[[Any], None]) -> dict[str, Any]:
    """The row is on and the list fails some other way, which must be met the same way as a row turned off."""

    def is_the_list(url: str) -> bool:
        return urlsplit(url).path == SYNC

    context = browser.new_context(viewport=WINDOW)
    asked: Counter[str] = Counter()
    context.on("request", lambda request: asked.update([urlsplit(request.url).path]))
    context.route(is_the_list, failure)
    page = context.new_page()
    page.set_default_timeout(60_000)
    page.goto(base, wait_until="domcontentloaded")
    market = open_marketplace(page)
    market.wait_for_selector(UNAVAILABLE)
    asked.clear()
    page.wait_for_timeout(WAITS_THROUGH)
    seen = {"asked": asked[SYNC], "words": words(market, UNAVAILABLE)}
    context.unroute(is_the_list)
    market.click(REFRESH)
    market.wait_for_selector(CARD)
    seen["words_after"] = market.locator(UNAVAILABLE).count()
    context.close()
    return seen


async def _window_answers(base: str, row: str, how: str) -> bool:
    """Do what a person does to a Marketplace tab, with a real mouse, and see whether the window is still there.

    Async, because a click on a frozen window is never acknowledged, and the sync API would wait for that for ever.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(viewport=WINDOW)
            await context.request.post(f"{base}/api/plugins/thomas/catalog/{row}", data={})
            if row == "on":
                # Never answered, so the ask is still out when the tab goes, as the first one is on a page just opened.
                await context.route(lambda url: urlsplit(url).path == SYNC, lambda route: None)
            page = await context.new_page()
            await page.goto(base, wait_until="domcontentloaded")
            await page.click(SIDEBAR_BUTTON)
            frame = await (await page.wait_for_selector(PAGE_FRAME)).content_frame()
            await frame.wait_for_selector(HEAD)
            await page.wait_for_timeout(1000)
            if how == "reload":
                acted = page.reload(wait_until="domcontentloaded")
            else:
                box = await page.locator(TAB_X).bounding_box()
                acted = page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, delay=80)
            await asyncio.wait_for(acted, FROZEN_AFTER)
            await page.wait_for_selector(".bt-tab:has-text('Chat')", timeout=FROZEN_AFTER * 1000)
            return how == "reload" or await page.locator(TAB_X).count() == 0
        except (TimeoutError, asyncio.TimeoutError):
            return False
        finally:
            await browser.close()


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One walk through the real page, for the tests below to read. Each step needs the one before it."""
    # With THOMAS_REQUIRE_BROWSER_TESTS=1 this raises, so a run that must have a browser cannot skip.
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    with serving(tmp_path_factory.mktemp("catalog-page")) as base, sync_playwright() as playwright:
        return walk(base, playwright.chromium.launch(headless=True))


@pytest.fixture(scope="module")
def a_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    with serving(tmp_path_factory.mktemp("catalog-window")) as base:
        yield base


@pytest.fixture(scope="module")
def failed(a_server: str) -> dict[str, Any]:
    """A server error and a dropped connection, each in a real browser. A 404 from a row turned off is the walk's."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        return {
            "server error": _after_a_failure_with_the_row_on(
                a_server, browser, lambda route: route.fulfill(status=500, body="The store fell over.")
            ),
            "dropped": _after_a_failure_with_the_row_on(a_server, browser, lambda route: route.abort()),
        }


def test_with_the_row_off_the_page_says_so_and_lists_nothing(walked: dict[str, Any]) -> None:
    """Exactly this and no more. If the page learns to say anything else here, this fails and the words must change.

    Inkwell is installed all through this, so a count of 0 installed would be the page being wrong, and none is shown.
    """
    assert walked["install"] == 200
    assert walked["cards_on"] > 0, "the page never filled in with the row on, so what it leaves out says nothing"
    assert walked["head_off"] == HEAD_OFF
    assert walked["list_off"] == ""
    assert walked["cards_off"] == 0


def test_a_normal_window_shows_the_words_without_scrolling(walked: dict[str, Any]) -> None:
    """In the page is not the same as on the screen, and the Plugged in section is tall enough to push them off it."""
    assert 0 <= walked["words_top"] < walked["words_bottom"] <= walked["window_height"]
    assert "Loading upgrades" not in walked["off_means"]


def test_after_a_failed_ask_the_page_waits_even_in_a_tab_you_have_left(walked: dict[str, Any]) -> None:
    """None at all in a wait that holds a redraw of the page's own. Without the wait this is about 600 of them."""
    assert walked["asked_on_the_page"] == 0
    assert walked["asked_from_another_tab"] == 0


@pytest.mark.parametrize("failure", ["server error", "dropped"])
def test_any_failed_ask_waits_and_says_so_and_a_press_still_asks(failed: dict[str, Any], failure: str) -> None:
    """A row turned off is the one failure anyone planned for, so the wait must not depend on it being a 404."""
    assert failed[failure]["asked"] == 0
    assert failed[failure]["words"].startswith("Marketplace unavailable.")
    assert failed[failure]["words_after"] == 0


def test_the_words_of_a_failed_ask_quote_what_went_wrong(failed: dict[str, Any]) -> None:
    assert "The store fell over." in failed["server error"]["words"]


@pytest.mark.parametrize(
    ("row", "how"),
    [("off", "close"), ("off", "reload"), ("on", "close"), ("on", "reload")],
    ids=["off, the x", "off, a window reload", "on with the list out, the x", "on with the list out, a window reload"],
)
def test_the_window_survives_the_page_going_away(a_server: str, row: str, how: str) -> None:
    """A frame that is going fails every ask at once, so a page that asked again after a failure never let go of the thread.

    It runs all this in one turn of the window's thread, and the whole window waits, for good.
    """
    assert asyncio.run(_window_answers(a_server, row, how))


def test_the_wheel_your_typing_and_a_normal_click_all_work(walked: dict[str, Any]) -> None:
    """Each is asked of the row on first, or nothing would show the page ever did any of them."""
    assert walked["scrolled_on"] > 0
    assert walked["scrolled_off"] > 0
    assert walked["typed"] == TYPED
    assert walked["prompts_on"] == 1
    assert walked["prompts_off"] == 1


def test_only_the_plugged_in_section_still_answers(walked: dict[str, Any]) -> None:
    assert walked["install_from_it"]["ok"] is False, walked["install_from_it"]
    assert walked["remove_from_it"]["ok"] is False, walked["remove_from_it"]
    assert "Plugged in" in walked["plugged_in_off"]
    assert walked["kernel_sync"] == 200


def test_after_a_reload_an_app_leaves_the_sidebar_and_library_and_nothing_says_why(walked: dict[str, Any]) -> None:
    assert "Inkwell" in walked["sidebar_on"]
    assert walked["sidebar_off"] == [name for name in walked["sidebar_on"] if name != "Inkwell"]
    assert "Inkwell" in walked["library_on"]
    assert "Inkwell" not in walked["library_off"]


def test_a_desktop_shortcut_to_an_app_shows_a_bare_404(walked: dict[str, Any]) -> None:
    assert walked["shortcut"] == (404, "404: Not Found")


def test_an_open_app_page_goes_on_working_until_you_reload_it(walked: dict[str, Any]) -> None:
    assert walked["note_from_the_open_app"] in {200, 201}
    assert walked["open_app_reloaded"] == (404, "404: Not Found")


def test_an_open_marketplace_page_keeps_its_list_through_a_failed_refresh(walked: dict[str, Any]) -> None:
    assert walked["cards_open"] == walked["cards_on"]
    assert walked["words_open"].startswith("Marketplace unavailable.")


def test_turned_back_on_the_page_fills_in_by_itself(walked: dict[str, Any]) -> None:
    """Nothing is pressed and the tab is left, so this is its next ask: 75 seconds, then the next of its 15 second redraws."""
    assert walked["pressed_on"] == 200
    assert 75 <= walked["asked_again_after"] <= 100
    assert walked["apps_back"] > 0
    assert walked["words_after_on"] == 0


def test_a_press_of_sync_catalog_does_not_wait(walked: dict[str, Any]) -> None:
    """The first ask with the row back on is slower than the rest, and the wait it must not sit out is 75 seconds."""
    assert walked["back_after_a_press_in"] < 30
