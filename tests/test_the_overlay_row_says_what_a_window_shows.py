"""The overlay row's words, read from a real window on a real server, with the row on, off, and on again.

These are the words of ``thomas.server.rows.overlay`` for the pages of ``thomas.server.routes.ui_overlay_routes``. Finding a
word in a page's HTML says it is in the page, not that a window shows it, so everything here is a computed style or a page
that opened. Redesign with AI, and the requests a page makes with the row off, are in
``tests/test_the_overlay_row_with_redesign_and_no_loops.py``. The saved file and the routes are in
``tests/test_turning_overlay_off_keeps_your_saved_changes.py`` and
``tests/test_turning_overlay_off_touches_only_its_routes.py``, and a save that is running when you press Stop now is in
``tests/test_turning_overlay_off_with_a_save_running.py``.

Every sentence of the words is in ``SENTENCES`` below with the tests that show it, and the last test fails when a sentence
is added, changed or dropped without this list.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest

from tests.overlay_window_fixture import (
    ON_LOOKS,
    SAVED,
    STATE,
    STOCK_LOOKS,
    WINDOW,
    ask,
    home,
    looks,
    open_from,
    press,
    redesign_menu,
    reload,
)
from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT, ROWS
from tests.web_fixtures.thomas_chat_fixture import browser_ok

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

WORDS = next(row for row in ROWS if row.id == "overlay").config["words"]
SIDEBAR = (
    "System",
    "Virtual Office",
    "Library",
    "Channels",
    "Token Economy",
    "Marketplace",
)
# The page each opens, and whether it carries your saved changes. The older full page is one frame four of them share.
CARRIES = {
    "System": [["/system", False]],
    "Virtual Office": [["/classic", True]],
    "Library": [["/my-stuff", False]],
    "Channels": [["/classic", True]],
    "Token Economy": [["/classic", True]],
    "Marketplace": [["/classic", True]],
}
FORGETTERS = {
    "Settings": "#tc-settings",
    "Library": "button:has-text('Library')",
    "Virtual Office": "button:has-text('Virtual Office')",
}
CARRIES_NONE = {name: [[page[0][0], False]] for name, page in CARRIES.items()}
PROOFS = (
    "test_the_overlay_row_says_what_a_window_shows.py",
    "test_the_overlay_row_with_redesign_and_no_loops.py",
    "test_turning_overlay_off_touches_only_its_routes.py",
    "test_turning_overlay_off_with_a_save_running.py",
)
SENTENCES = {
    "Keeps the changes you save to how Thomas looks, such as a colour, a theme, the name it answers to, or the size and "
    "place of a part of a page, and puts them on Chat, Settings and the older full page that Virtual "
    "Office, Channels, Token Economy and Marketplace open in, each time they open.": (
        "test_with_the_row_on_a_window_shows_every_kind_of_saved_change",
        "test_the_pages_in_the_sidebar_and_settings_carry_them_with_the_row_on",
    ),
    "System and Library do not show them.": ("test_the_pages_in_the_sidebar_and_settings_carry_them_with_the_row_on",),
    "Redesign with AI, in the menu of the plus button beside your message box in Chat, is what saves them.": (
        "test_redesign_with_ai_is_in_the_plus_menu_and_saves_to_them",
    ),
    "While this is off, every page you open comes up as Thomas ships it, with none of your saved changes.": (
        "test_with_the_row_off_a_new_window_shows_thomas_as_it_ships",
        "test_the_pages_in_the_sidebar_and_settings_carry_none_with_the_row_off",
    ),
    "Nothing is deleted, and when you turn this back on the pages you open next show every saved change exactly as "
    "before.": ("test_turned_back_on_a_new_window_shows_every_saved_change_and_the_theme_is_still_there",),
    "Opening Settings, Library or Virtual Office while this is off makes this browser forget which of "
    "your saved themes you had chosen, so choose it again once this is back on.": (
        "test_opening_a_page_with_the_row_off_makes_the_browser_forget_your_chosen_theme",
    ),
    "A page already open keeps its look until you reload it.": (
        "test_a_page_already_open_keeps_its_look_until_reloaded",
    ),
    "Redesign with AI still opens, but a change to a colour or a name is not applied, and a change to a part of a page "
    "shows only in this browser.": ("test_redesign_with_ai_opens_but_applies_only_a_part_of_a_page_here",),
    "Its note then says to reload and Apply again, or to restart Thomas, and neither helps while this is off.": (
        "test_redesign_with_ai_opens_but_applies_only_a_part_of_a_page_here",
        "test_a_page_already_open_blames_the_server_and_a_new_one_blames_the_page",
    ),
    "Other programs cannot read or change your saved changes through Thomas.": (
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
    ),
    "If a save is under way when you turn this off, Thomas waits for it to finish.": (
        "test_a_save_holds_the_switch_until_it_ends",
    ),
}


def in_the_sidebar(page: Any, names: tuple[str, ...]) -> dict[str, list[list[Any]]]:
    """Press each name in the sidebar itself: the mode menu lists some of the same names, hidden until it opens."""
    return {name: open_from(page, f"#tc-workspaces button:has-text('{name}')") for name in names}


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    folder = tmp_path_factory.mktemp("overlay-window")
    seen: dict[str, Any] = {}
    with serving(folder) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yours = browser.new_context(viewport=WINDOW)  # one browser, so the theme you chose is kept between windows
        seed = {"overlay_id": None, "action": {"actor": "test", "instruction": "seed", "targets": []}, "records": SAVED}
        status, body = ask(base, "/api/ui/overlay/records", seed)
        assert status == 200, body

        page = home(browser, base, context=yours)
        page.evaluate("() => localStorage.setItem('thomas_chat_theme', 'ember')")
        page.reload()
        page.wait_for_selector("#tc-shell")
        page.wait_for_timeout(1500)
        seen["on"] = page.evaluate(STATE)
        seen["on_frames"] = in_the_sidebar(page, SIDEBAR)
        seen["on_settings"] = open_from(page, "#tc-settings")
        page.close()

        page = home(browser, base, context=yours)
        seen["on_menu"] = redesign_menu(page)
        page.close()

        open_page = home(browser, base, context=yours)
        seen["open_before"] = open_page.evaluate(STATE)
        press(base, "off")
        seen["open_after_off"] = open_page.evaluate(STATE)
        seen["open_reloaded"] = reload(open_page)

        fresh = home(browser, base, context=yours)
        seen["off"] = fresh.evaluate(STATE)
        seen["off_frames"] = in_the_sidebar(fresh, SIDEBAR)
        seen["off_settings"] = open_from(fresh, "#tc-settings")
        fresh.close()

        seen["forgets"] = {}
        for name, button in FORGETTERS.items():
            window = browser.new_context(viewport=WINDOW)
            page = home(browser, base, context=window)
            page.evaluate("() => localStorage.setItem('thomas_chat_theme', 'ember')")
            before = page.evaluate("() => localStorage.getItem('thomas_chat_theme')")
            open_from(page, button)
            seen["forgets"][name] = [before, page.evaluate("() => localStorage.getItem('thomas_chat_theme')")]
            window.close()

        press(base, "on")
        fresh = home(browser, base, context=yours)
        seen["on_again"] = fresh.evaluate(STATE)
        seen["on_again_frames"] = in_the_sidebar(fresh, SIDEBAR)
        fresh.close()
        browser.close()
        yield seen


def test_with_the_row_on_a_window_shows_every_kind_of_saved_change(walked: dict[str, Any]) -> None:
    assert looks(walked["on"], ON_LOOKS) == ON_LOOKS
    assert walked["on"]["asks"].startswith("Message Otto")
    assert walked["on"]["theme"] == "ember" and walked["on"]["bg"] == "#140a06"


def test_the_pages_in_the_sidebar_and_settings_carry_them_with_the_row_on(walked: dict[str, Any]) -> None:
    assert walked["on_frames"] == CARRIES
    assert walked["on_settings"] == [["/settings", True]]


def test_redesign_with_ai_is_in_the_plus_menu_and_saves_to_them(walked: dict[str, Any]) -> None:
    assert walked["on_menu"] == {"words": "Redesign with AI", "title": "Create or add", "phase": "selecting"}


def test_with_the_row_off_a_new_window_shows_thomas_as_it_ships(walked: dict[str, Any]) -> None:
    assert looks(walked["off"], STOCK_LOOKS) == STOCK_LOOKS
    assert walked["off"]["asks"].startswith("Message Thomas")
    assert walked["off"]["theme"] == "nebula"


def test_the_pages_in_the_sidebar_and_settings_carry_none_with_the_row_off(walked: dict[str, Any]) -> None:
    assert walked["off_frames"] == CARRIES_NONE
    assert walked["off_settings"] == [["/settings", False]]


def test_turned_back_on_a_new_window_shows_every_saved_change_and_the_theme_is_still_there(
    walked: dict[str, Any],
) -> None:
    """Every look is back. Which theme is chosen is the browser's own, and the next test is about that."""
    ignoring = ("theme", "bg", "chosen")
    assert {k: v for k, v in walked["on_again"].items() if k not in ignoring} == {
        k: v for k, v in walked["on"].items() if k not in ignoring
    }
    assert walked["off"]["knows_ember"] is False and walked["on_again"]["knows_ember"] is True
    assert walked["on_again_frames"] == CARRIES


def test_a_page_already_open_keeps_its_look_until_reloaded(walked: dict[str, Any]) -> None:
    assert walked["open_after_off"] == walked["open_before"]
    assert looks(walked["open_after_off"], ON_LOOKS) == ON_LOOKS
    assert looks(walked["open_reloaded"], STOCK_LOOKS) == STOCK_LOOKS


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    """The words are what you are told, so none lands on the strength of having been true once."""
    written = [*re.split(r"(?<=\.)\s+", WORDS["about"]), *re.split(r"(?<=\.)\s+", WORDS["off_means"])]
    assert written == list(SENTENCES)
    proofs = "".join((ROOT / "tests" / name).read_text(encoding="utf-8") for name in PROOFS)
    named = {name for names in SENTENCES.values() for name in names}
    assert {name for name in named if f"def {name}(" not in proofs} == set()


def test_opening_a_page_with_the_row_off_makes_the_browser_forget_your_chosen_theme(walked: dict[str, Any]) -> None:
    """Each page rewrites the choice as the nearest theme it knows, which is the stock one, while its own theme is gone."""
    assert walked["on"]["chosen"] == "ember"
    assert walked["forgets"] == {name: ["ember", "nebula"] for name in FORGETTERS}
    assert walked["on_again"]["chosen"] == "nebula" and walked["on_again"]["theme"] == "nebula"
