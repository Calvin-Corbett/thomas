"""The results page says what happened, on a wide window and a narrow one.

A search has four honest endings -- results, nothing found, a provider that
failed, and a slow answer overtaken by a newer query -- and the page has to
show which one it is. Driven through ``tests/web_node/browser_search_playtest.html``,
which stubs only the service boundary: the markup, layout, fetch/abort and
page lifecycle are the shipped ``browser_shell_search.js``.

That page is also the fixture a person opens by hand to look at Search, so the
run leaves screenshots of both widths beside the other browser proofs.
"""

from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "tests" / "web_node" / "browser_search_playtest.html"
PROOFS = REPO_ROOT / ".thomas" / "playtest"

pytestmark = pytest.mark.skipif(not PAGE.exists(), reason="the Search fixture is not present in this checkout")


def _serve_repo():
    """Serve the checkout on loopback so the page can load the real CSS and JS."""
    from tests.web_fixtures.thomas_chat_fixture import QuietHTTPServer

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

        def log_message(self, *_args) -> None:  # keep pytest output clean
            return

    server = QuietHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_the_search_page_answers_in_every_state() -> None:
    from tests.web_fixtures.thomas_chat_fixture import browser_ok

    if not browser_ok():
        pytest.skip("Chromium unavailable; open the HTML fixture with web.playtest instead")
    from playwright.sync_api import sync_playwright

    PROOFS.mkdir(parents=True, exist_ok=True)
    server, thread = _serve_repo()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/tests/web_node/{PAGE.name}")

                # Results, with the overview beside them and nothing cut off.
                page.locator(".bt-sr-title").first.wait_for()
                assert page.locator(".bt-sr-title").count() == 2
                assert "Thomas overview" in page.locator(".bt-ai").inner_text()
                assert page.locator(".bt-ai-body").inner_text().startswith("Thomas Search keeps")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(PROOFS / "search-page-wide.png"), full_page=True)

                # The same page on a phone: the overview moves above the rows,
                # the search box stays reachable, and nothing scrolls sideways.
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.locator(".bt-sr-form input").is_visible()
                page.screenshot(path=str(PROOFS / "search-page-narrow.png"), full_page=True)

                # Nothing found says so, rather than showing an empty page that
                # reads as a search that never ran.
                page.locator(".bt-sr-form input").fill("no results")
                page.locator(".bt-sr-form input").press("Enter")
                page.get_by_text("No results found").wait_for()
                page.screenshot(path=str(PROOFS / "search-page-no-results.png"), full_page=True)

                # A failed provider says why and offers the retry, and the retry
                # actually brings the results back.
                page.evaluate("window.fixture.failNext()")
                page.locator(".bt-sr-form input").fill("retry query")
                page.locator(".bt-sr-form input").press("Enter")
                page.get_by_text("Couldn’t load results").wait_for()
                page.screenshot(path=str(PROOFS / "search-page-failed.png"), full_page=True)
                page.get_by_role("button", name="Try again").click()
                page.locator(".bt-sr-title").first.wait_for()

                # A slow search overtaken by a newer one must never replace it:
                # the answer you are reading would swap under you for a query
                # you had already moved on from.
                page.locator(".bt-sr-form input").fill("slow first")
                page.locator(".bt-sr-form input").press("Enter")
                page.locator(".bt-sr-form input").fill("fast second")
                page.locator(".bt-sr-form input").press("Enter")
                page.locator(".bt-sr-title").first.wait_for()
                page.wait_for_timeout(800)  # past the slow response
                assert page.locator(".bt-sr-q").inner_text() == "Results for “fast second”"
                assert page.locator(".bt-sr-title").first.inner_text().startswith("fast second")

                # And a row opens the source it names.
                page.locator(".bt-sr-title").first.click()
                assert "https://example.com/docs" in page.locator(".bt-sr-q").inner_text()
                assert not errors, errors
            finally:
                browser.close()
    finally:
        server.close_quietly(thread)
