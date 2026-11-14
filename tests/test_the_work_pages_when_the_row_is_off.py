"""The System page, Work and Virtual Office with the work row off, in a real browser on a real server, and with it on.

The row is ``thomas.server.rows.work``, and its routes are in ``thomas.server.routes.mission`` and
``thomas.server.routes.work``. The pages that ask for them are ``system_page.js`` (the System page, opened from the
sidebar), ``unified_work_mode.js`` (Work, next to Chat and Build), ``023_mission_control_01.js`` and
``024_mission_control_02.js`` (the Mission Control panels inside the older full page) and ``019_virtual_office_03.js``
(the live stream Virtual Office opens). Those names are how a check finds this file when one of them changes. Each window is read
for ten seconds with the row on and then with it off, and what is counted is every request to a Mission or Work route.
The words say what you see, and reading a file for a word says nothing of that: it can sit where no window shows it.

The routes and the guard are in ``tests/test_turning_work_off_touches_only_its_routes.py``, and each sentence of the
words is listed in ``tests/test_the_work_words_are_held.py`` with the test that shows it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.row_page_fixture import serving
from tests.web_fixtures.thomas_chat_fixture import browser_ok

WINDOW = {"width": 1366, "height": 768}
TEN_SECONDS = 10_000


def _ours(path: str) -> bool:
    return path.startswith("/api/mission") or path.startswith("/api/work/")


def _watch(
    server: str, browser: Any, row: str, open_it: Callable[[Any], None], pause: int = TEN_SECONDS
) -> dict[str, Any]:
    """Open one window on a server with the row pressed ``row``, and read it after ``pause`` milliseconds."""
    context = browser.new_context(viewport=WINDOW)
    context.request.post(f"{server}/api/plugins/thomas/work/{row}", data={})
    asked: Counter[str] = Counter()
    refused: Counter[tuple[str, int]] = Counter()
    context.on("request", lambda r: asked.update([urlsplit(r.url).path]) if _ours(urlsplit(r.url).path) else None)
    context.on(
        "response",
        lambda r: (
            refused.update([(urlsplit(r.url).path, r.status)])
            if _ours(urlsplit(r.url).path) and r.status >= 400
            else None
        ),
    )
    page = context.new_page()
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    asked.clear()
    refused.clear()
    open_it(page)
    page.wait_for_timeout(pause)
    frame = next(f for f in page.frames if f != page.main_frame and f.url.startswith(server) and "/api/" not in f.url)
    seen = {
        "asked": sum(asked.values()),
        "refused": {path for (path, _status), _n in refused.items()},
        "text": frame.evaluate("document.body.innerText"),
        "frame": frame,
        "context": context,
    }
    return seen


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    found: dict[str, dict[str, Any]] = {}
    windows = {
        "system": lambda p: p.click("button[data-bt-mode='system']"),
        "office": lambda p: p.click("button[data-bt-mode='office']"),
        "work": lambda p: p.click("button[data-thomas-mode='work']"),
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for row in ("on", "off"):
            with serving(tmp_path_factory.mktemp(f"work-pages-{row}")) as server:
                for name, open_it in windows.items():
                    seen = _watch(server, browser, row, open_it)
                    frame = seen.pop("frame")
                    seen.pop("context")
                    if name == "system":
                        # Turning to another page: a window that is frozen never answers this.
                        frame.click("[data-go='tasks']", timeout=5000)
                        frame.wait_for_selector("h2:has-text('Tasks')", timeout=5000)
                        seen["tasks"] = frame.evaluate("document.body.innerText")
                        seen["usable"] = True
                    if name == "work":
                        colour = frame.locator("text=Work returned an unreadable response").first
                        seen["red"] = colour.evaluate("e => getComputedStyle(e).color") if colour.count() else ""
                    found[f"{name} {row}"] = seen
        browser.close()
    return found


def test_system_opens_and_its_tasks_page_says_the_list_could_not_be_read(walked: dict[str, dict[str, Any]]) -> None:
    off, on = walked["system off"], walked["system on"]
    assert "Overview" in off["text"] and "Overview" in on["text"], "the page opens either way"
    assert "The task list could not be read just now." in off["tasks"]
    assert "could not be read" not in on["tasks"] and "Tasks" in on["tasks"]
    assert "/api/mission/control" in off["refused"]
    assert on["refused"] == set()


def test_system_asks_again_every_five_seconds_and_stays_usable(
    walked: dict[str, dict[str, Any]],
) -> None:
    # Once as it opens, then at five seconds and at ten: two or three in a ten-second look, never a storm.
    assert 2 <= walked["system off"]["asked"] <= 4, walked["system off"]["asked"]
    assert walked["system off"]["usable"] is True


def test_work_opens_with_no_jobs_and_says_it_got_an_unreadable_response(walked: dict[str, dict[str, Any]]) -> None:
    off, on = walked["work off"], walked["work on"]
    assert "Work returned an unreadable response (404)" in off["text"] and "No jobs yet." in off["text"]
    assert "unreadable response" not in on["text"] and "No jobs yet." in on["text"]
    red, green, _blue = (int(part) for part in off["red"].removeprefix("rgb(").rstrip(")").split(",")[:3])
    assert red > 200 and green < 160, off["red"]
    assert {"/api/work/apps", "/api/work/accounts", "/api/work/connectors"} <= off["refused"]
    assert off["asked"] <= 8  # each list is asked for once


def test_virtual_office_keeps_its_rooms_and_gets_no_live_updates(walked: dict[str, dict[str, Any]]) -> None:
    off, on = walked["office off"], walked["office on"]
    for text in (off["text"], on["text"]):
        # innerText follows the page's capital letters, which change once its stylesheet has loaded.
        assert "strategy room" in text.lower() and "active roster" in text.lower()
    assert "/api/mission/stream" in off["refused"]
    assert "/api/mission/stream" not in on["refused"]
    assert off["asked"] <= 20, off["asked"]  # it keeps trying, and slows down
