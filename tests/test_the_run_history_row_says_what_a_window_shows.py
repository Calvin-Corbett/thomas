"""The run history row's words about pages, held in a real browser with the real switch pressed.

The row ``thomas.server.rows.runs`` holds the routes of ``thomas.server.routes.runs``. One script fetches one of them, for
the Runs tab of the Tools Console on the older full page, and nothing else in the web layer names them. So the words say
that nothing you normally use changes, and what that one tab reads once it refreshes. A failed fetch can redraw a page and
ask again, which froze a window on the Marketplace, so the walk below counts what the pages ask for as well as what they
show.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.open_the_plugin_list import open_the_plugin_list
from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT, ROWS
from tests.web_fixtures.thomas_chat_fixture import browser_ok
from thomas.marketplace.observability import run_store

WINDOW = {"width": 1600, "height": 900}
TITLE = "Run history for other programs"
UNAVAILABLE = "Run store endpoint is not available in this environment."
# How long each page is watched. Ten seconds was measured by hand on every page. This stays in a test's budget.
WATCH_MS = 3000
EMBEDDED = ("/classic?embed=1", "/agents?embed=1", "/settings?embed=1")


def _record_a_run(memory: Any) -> None:
    """Into the store the server has open, the way a turn writes it, and let go again."""
    run_store.init_db(memory / ".thomas" / "runs.sqlite3")
    try:
        run_store.create_run({"run_id": "a-recorded-run", "session_id": "s1", "mode": "chat"})
        run_store.finalize_run("a-recorded-run", ok=True, error=None, iterations=1, tool_calls=0, usage=None)
    finally:
        run_store.shutdown(reset_db_path=True)


def _open_the_runs_tab(page: Any) -> None:
    # On a new install Easy Setup comes up by itself and closes the console, so it goes first.
    skip = page.locator("button:has-text('Skip for now')")
    skip.wait_for(state="visible")
    skip.click()
    skip.wait_for(state="hidden")
    page.wait_for_timeout(1500)
    page.click("#debugDockToggleBtn")
    page.wait_for_selector(".debug-dock-open")
    page.wait_for_timeout(800)
    page.locator("#debugTabRuns").evaluate("(tab) => tab.focus()")  # the strip of tabs is wider than the console
    page.locator("#debugTabRuns").click()
    _settled(page)


def _settled(page: Any) -> None:
    page.wait_for_timeout(300)
    page.wait_for_function("() => debugLiveLoading === false", timeout=90_000)
    page.wait_for_timeout(300)


def _tab(page: Any) -> tuple[str, str, str]:
    return tuple(
        page.locator(selector).inner_text().strip()
        for selector in ("#debugRunsCount", "#debugRunsFailed", "#debugRunsList")
    )


def _press(settings: Any, wanted: str) -> None:
    row = settings.locator(".plugin-row", has_text=TITLE)
    row.locator(".toggle-switch").click()
    row.locator(f".plugin-state:has-text('{wanted}')").wait_for()


def _walk(base: str, browser: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    context = browser.new_context(viewport=WINDOW)
    asked: Counter[str] = Counter()
    context.on("request", lambda request: asked.update([urlsplit(request.url).path]))
    page = context.new_page()
    page.set_default_timeout(60_000)
    page.goto(f"{base}/classic", wait_until="domcontentloaded")
    _open_the_runs_tab(page)
    seen["on"] = _tab(page)

    settings = context.new_page()
    settings.set_default_timeout(60_000)
    settings.goto(f"{base}/settings?section=plugins", wait_until="domcontentloaded")
    open_the_plugin_list(settings)
    settings.locator(".plugin-row", has_text=TITLE).wait_for()
    _press(settings, "Off")

    page.bring_to_front()
    asked.clear()
    page.wait_for_timeout(WATCH_MS)
    seen["open_after_off"] = _tab(page)
    seen["asked_while_open"] = asked["/api/runs"]
    page.click("#debugDockRefreshBtn")
    _settled(page)
    seen["refreshed"] = _tab(page)
    seen["asked_by_a_refresh"] = asked["/api/runs"]
    asked.clear()
    page.wait_for_timeout(WATCH_MS)
    seen["asked_after_a_refresh"] = asked["/api/runs"]

    seen["asked_by_a_page"] = {}
    for path in EMBEDDED:
        other = context.new_page()
        asked.clear()
        other.goto(f"{base}{path}", wait_until="domcontentloaded")
        other.wait_for_timeout(WATCH_MS)
        seen["asked_by_a_page"][path] = asked["/api/runs"]
        other.close()

    agents = context.new_page()
    agents.set_default_timeout(60_000)
    agents.goto(f"{base}/agents?embed=1#tasks", wait_until="domcontentloaded")
    agents.locator("text=Chat Session").first.wait_for()
    seen["agents"] = agents.locator("body").inner_text()

    settings.bring_to_front()
    _press(settings, "On")
    page.bring_to_front()
    page.click("#debugDockRefreshBtn")
    _settled(page)
    seen["back_on"] = _tab(page)
    return seen


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One walk through the real pages, for the tests below to read. Each step needs the one before it."""
    # With THOMAS_REQUIRE_BROWSER_TESTS=1 this raises, so a run that must have a browser cannot skip.
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    folder = tmp_path_factory.mktemp("runs-page")
    with serving(folder) as base, sync_playwright() as playwright:
        _record_a_run(folder / "memory")
        return _walk(base, playwright.chromium.launch(headless=True))


def _words() -> str:
    return next(row for row in ROWS if row.id == "runs").config["words"]["off_means"]


def test_the_tab_keeps_what_it_last_showed_and_asks_for_nothing_until_it_refreshes(walked: dict[str, Any]) -> None:
    assert walked["on"][:2] == ("1", "0")
    assert "a-recorded" in walked["on"][2]
    assert walked["open_after_off"] == walked["on"]
    assert walked["asked_while_open"] == 0
    assert "the Runs tab of its Tools Console keeps what it last showed until it next refreshes" in _words()


def test_a_refresh_with_the_row_off_reads_nothing_and_blames_the_environment(walked: dict[str, Any]) -> None:
    assert walked["refreshed"] == ("0", "0", UNAVAILABLE)
    assert (
        "reads 0 listed and 0 failed and says the run store endpoint is not available in this environment" in _words()
    )


def test_with_the_row_off_a_refresh_asks_once_and_no_page_asks_at_all(walked: dict[str, Any]) -> None:
    assert (walked["asked_by_a_refresh"], walked["asked_after_a_refresh"]) == (1, 0)
    assert walked["asked_by_a_page"] == dict.fromkeys(EMBEDDED, 0)


def test_the_agents_page_goes_on_listing_runs_with_the_row_off(walked: dict[str, Any]) -> None:
    assert "Chat Session" in walked["agents"]
    assert "the System page goes on listing the recent ones" in _words()


def test_on_brings_the_tab_back_at_its_next_refresh(walked: dict[str, Any]) -> None:
    assert walked["back_on"] == walked["on"]


def test_no_page_in_the_sidebar_or_settings_reads_these_routes() -> None:
    """The row's words tell you nothing you normally use changes. One script fetches one of these routes, for one tab.

    That tab opens from a button on the older full page, and everything that opens the older page asks for it embedded,
    which hides both the button and the console. ``tests/test_turning_memory_routes_off_touches_only_its_routes.py`` holds
    that second half for the same console. If a new page calls these routes, this fails and those words have to change.
    """
    web = ROOT / "thomas" / "server" / "web"
    named = {
        path.name: re.findall(r"/api/runs[^'\"`]*", path.read_text(encoding="utf-8"))
        for path in (*web.rglob("*.js"), *web.rglob("*.html"))
        if "/api/runs" in path.read_text(encoding="utf-8")
    }

    assert named == {"015_debug_dock.js": ["/api/runs?limit=12"]}
    assert UNAVAILABLE in (web / "js" / "runtime" / "015_debug_dock.js").read_text(encoding="utf-8")
    assert (
        "No page in the sidebar or Settings uses this."
        in next(row for row in ROWS if row.id == "runs").config["words"]["about"]
    )
