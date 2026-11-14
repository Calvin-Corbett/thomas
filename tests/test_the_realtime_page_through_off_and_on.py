"""The realtime page in a real browser, on a real server, with its row on, off and on again.

The row's words say what a window shows, so this reads what a window shows. It opens ``/realtime`` the way you would, by
its address, presses Connect, and turns the row off and on underneath it. The page's code is ``realtime.js`` and
``ws_client.js``, and those names are how a check finds this file when one of them changes. It also counts what the page
asks for with the row off, because a page that asks without end can freeze a window, and this one must not.

``thomas.server.rows.realtime`` is the row and ``thomas.marketplace.realtime.routes`` serves the page, named here because
no test imports a row, and a check finds a test by the names in it.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT
from tests.web_fixtures.thomas_chat_fixture import browser_ok
from thomas.server.proof.selection import select

SWITCH = "/api/plugins/thomas/realtime"
A_NORMAL_WINDOW = {"width": 1366, "height": 768}
TEN_SECONDS = 10_000
THREE_SECONDS = 3_000
# Counted in the page, because a socket refused at its handshake never reaches the browser's list of requests.
_COUNT_SOCKETS = """
window.socketsMade = 0;
const RealSocket = window.WebSocket;
window.WebSocket = new Proxy(RealSocket, {construct(real, args) { window.socketsMade += 1; return new real(...args); }});
"""


def _said(page: Any) -> dict[str, Any]:
    return {
        "status": page.inner_text("#status"),
        "button": page.inner_text("#connectBtn"),
        "banner": page.inner_text("#banner") if page.is_visible("#banner") else None,
    }


def _sockets_over(page: Any, wait: int) -> int:
    before = page.evaluate("window.socketsMade")
    page.wait_for_timeout(wait)
    return page.evaluate("window.socketsMade") - before


def _sockets_over_ten_seconds(page: Any) -> int:
    return _sockets_over(page, TEN_SECONDS)


def _banner_starts(page: Any, words: str) -> None:
    page.wait_for_function("(words) => document.getElementById('banner').textContent.startsWith(words)", arg=words)


def _walk(base: str, browser: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    page = browser.new_page(viewport=A_NORMAL_WINDOW)
    page.add_init_script(_COUNT_SOCKETS)
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url))

    seen["opened"] = page.goto(f"{base}/realtime", wait_until="load").status
    seen["heading"] = page.inner_text(".title")
    seen["before_connect"] = _said(page)
    page.click("#connectBtn")
    _banner_starts(page, "disabled:")
    seen["connect_pressed"] = _said(page)
    seen["sockets_on"] = _sockets_over_ten_seconds(page)
    seen["still_on"] = _said(page)

    page.click("#connectBtn")
    seen["sockets_after_second_press"] = _sockets_over(page, THREE_SECONDS)
    seen["after_second_press"] = _said(page)
    made = page.evaluate("window.socketsMade")
    page.click("#connectBtn")
    page.wait_for_function("(made) => window.socketsMade > made", arg=made)

    asked.clear()
    assert page.request.post(f"{base}{SWITCH}/off").status == 200
    _banner_starts(page, "WebSocket error")
    seen["row_off"] = _said(page)
    seen["sockets_off_first"] = _sockets_over_ten_seconds(page)
    seen["sockets_off_then"] = _sockets_over_ten_seconds(page)
    seen["requests_off"] = [url for url in asked if not url.endswith(f"{SWITCH}/off")]

    page.fill("#input", "Is anyone there?")
    page.click("#sendBtn")
    page.wait_for_timeout(1000)
    seen["sent_off"] = page.inner_text("#stream")
    seen["after_sending_off"] = _said(page)

    typed = browser.new_page(viewport=A_NORMAL_WINDOW)
    answer = typed.goto(f"{base}/realtime", wait_until="load")
    seen["typed_off"] = (answer.status, typed.inner_text("body"))
    typed.close()

    assert page.request.post(f"{base}{SWITCH}/on").status == 200
    _banner_starts(page, "disabled:")
    seen["row_back"] = _said(page)
    seen["sockets_back"] = _sockets_over_ten_seconds(page)

    assert page.request.post(f"{base}{SWITCH}/off").status == 200
    answer = page.reload(wait_until="load")
    seen["reloaded_off"] = (answer.status, page.inner_text("body"))
    page.close()
    return seen


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    if (ROOT / "runtime" / ".thomas" / "realtime.toml").exists():
        pytest.skip("this checkout has the feature's own settings file, so this is not the page as it ships")
    from playwright.sync_api import sync_playwright

    with serving(tmp_path_factory.mktemp("realtime-page")) as base, sync_playwright() as playwright:
        return _walk(base, playwright.chromium.launch(headless=True))


def test_the_page_is_headed_the_way_the_words_say(walked: dict[str, Any]) -> None:
    assert walked["opened"] == 200
    assert walked["heading"] == "Realtime Human Assistant Layer"
    assert walked["before_connect"] == {"status": "disconnected", "button": "Connect", "banner": None}


def test_as_shipped_connect_shows_a_warning_and_keeps_trying_about_twice_a_second(walked: dict[str, Any]) -> None:
    """The server says it is disabled and closes, and ``ws_client.js`` tries again after about half a second.

    Each try opens, so its count of tries goes back to nothing and the wait never grows: ten seconds hold about twenty.
    """
    assert walked["connect_pressed"]["status"] == "disconnected"
    assert walked["connect_pressed"]["banner"].startswith("disabled: Realtime layer is disabled.")
    assert 10 <= walked["sockets_on"] <= 30
    assert walked["still_on"] == walked["connect_pressed"]


def test_pressing_connect_a_second_time_stops_it_and_leaves_the_warning(walked: dict[str, Any]) -> None:
    assert walked["sockets_after_second_press"] == 0
    assert walked["after_second_press"] == walked["connect_pressed"]


def test_a_page_still_open_says_text_works_and_nothing_answers_it(walked: dict[str, Any]) -> None:
    """Its own banner says so, and that is false with the row off: your words appear and nothing comes back."""
    assert walked["row_off"] == {
        "status": "disconnected",
        "button": "Connect",
        "banner": "WebSocket error. Will retry automatically. Text mode still works.",
    }
    assert "Is anyone there?" in walked["sent_off"]
    assert "assistant" not in walked["sent_off"]
    assert walked["after_sending_off"] == walked["row_off"]


def test_a_page_still_open_settles_to_one_try_about_every_eight_seconds_and_does_not_loop(
    walked: dict[str, Any],
) -> None:
    """A switch on the Plugins page must not be able to freeze a window, as the Marketplace page did at 28 times a second.

    Its wait starts near half a second and grows to eight, so the first ten seconds hold a few tries and the next one or
    two. It asks for nothing else, because every other request it makes follows a press of yours.
    """
    assert 1 <= walked["sockets_off_first"] <= 6
    assert 1 <= walked["sockets_off_then"] <= 2
    assert walked["requests_off"] == []


def test_typing_its_address_or_reloading_it_with_the_row_off_shows_a_bare_404(walked: dict[str, Any]) -> None:
    assert walked["typed_off"] == (404, "404: Not Found")
    assert walked["reloaded_off"] == (404, "404: Not Found")


def test_a_page_still_open_goes_back_to_trying_about_twice_a_second_once_the_row_is_back_on(
    walked: dict[str, Any],
) -> None:
    assert walked["row_back"] == walked["connect_pressed"]
    assert 10 <= walked["sockets_back"] <= 30


@pytest.mark.parametrize("script", ["realtime.js", "ws_client.js"])
def test_a_change_to_the_page_runs_what_holds_its_words(script: str) -> None:
    """A check finds this file by those names in its text, so losing one would leave the page free to drift from the words."""
    assert "tests/test_the_realtime_page_through_off_and_on.py" in select(ROOT, [f"web/static/realtime/{script}"]).files
