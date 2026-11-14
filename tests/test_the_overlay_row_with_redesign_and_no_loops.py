"""Redesign with AI with the overlay row off, and what every page asks for in ten seconds.

These are the words of ``thomas.server.rows.overlay`` about Redesign with AI, and the check that a switch on the Plugins page
cannot freeze a window: the Marketplace page asked 28 times a second with its row off. Redesign's own reply is canned, so
what is read is what the page does with it. How the pages look is in
``tests/test_the_overlay_row_says_what_a_window_shows.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.overlay_window_fixture import (
    ON_LOOKS,
    PAGES,
    SAVED,
    SETTLED_MOST,
    STATE,
    STOCK_LOOKS,
    ask,
    home,
    looks,
    press,
    redesign_menu,
    redesign_note,
    watch,
    watch_open,
)
from tests.row_page_fixture import serving
from tests.web_fixtures.thomas_chat_fixture import browser_ok

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    folder = tmp_path_factory.mktemp("overlay-redesign")
    seen: dict[str, Any] = {}
    with serving(folder) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        seed = {"overlay_id": None, "action": {"actor": "test", "instruction": "seed", "targets": []}, "records": SAVED}
        status, body = ask(base, "/api/ui/overlay/records", seed)
        assert status == 200, body

        open_page = home(browser, base, canned=True)
        press(base, "off")
        seen["open_note"] = redesign_note(open_page)
        seen["open_after_apply"] = open_page.evaluate(STATE)

        page = home(browser, base)
        seen["off_menu"] = redesign_menu(page)
        page.close()

        page = home(browser, base, canned=True)
        seen["off_note"] = redesign_note(page)
        seen["off_after_apply"] = page.evaluate(STATE)
        page.close()

        seen["watched"] = {path: watch(browser, base, path) for path in PAGES}
        seen["watched_open"] = watch_open(open_page)
        browser.close()
        yield seen


def test_redesign_with_ai_opens_but_applies_only_a_part_of_a_page_here(walked: dict[str, Any]) -> None:
    """In a window opened with the row off: the sidebar changes in this browser, and the colour and the name do not."""
    assert walked["off_menu"]["phase"] == "selecting"
    note = walked["off_note"]
    assert "Kept in this browser only" in note
    assert "The theme changes were not applied." in note
    assert "this page predates the overlay runtime; reload and Apply again" in note
    after = walked["off_after_apply"]
    assert after["width"] == "400px" and after["sidebar"] == "rgb(85, 34, 0)"
    assert looks(after, {"accent": ""}) == {"accent": STOCK_LOOKS["accent"]}
    assert after["asks"].startswith("Message Thomas")


def test_a_page_already_open_blames_the_server_and_a_new_one_blames_the_page(walked: dict[str, Any]) -> None:
    assert "this server predates the overlay endpoint; restart it and Apply again" in walked["open_note"]
    assert "The theme changes were not applied." in walked["open_note"]
    # Nothing was saved, so the colour and the name it asked for are not there.
    assert looks(walked["open_after_apply"], {"accent": ""}) == {"accent": ON_LOOKS["accent"]}
    assert walked["open_after_apply"]["asks"].startswith("Message Otto")


def test_no_page_asks_for_the_routes_in_ten_seconds_and_none_loops(walked: dict[str, Any]) -> None:
    """With the row off, nothing a page does reaches the routes, so a caller finds them gone and does not try again."""
    assert {path: found["routes"] for path, found in walked["watched"].items()} == dict.fromkeys(PAGES, 0)
    assert walked["watched_open"]["routes"] == 0
    assert max(found["settled"] for found in walked["watched"].values()) <= SETTLED_MOST, walked["watched"]
    assert walked["watched_open"]["settled"] <= SETTLED_MOST, walked["watched_open"]
