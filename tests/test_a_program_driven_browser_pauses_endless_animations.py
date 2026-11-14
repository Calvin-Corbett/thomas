"""A browser a program drives pauses the Chat page's never-ending animations; a person's browser never does.

Measured 2026-11-06 (CPU research for your "cpu is still capped at 100%"): one idle Chat page in headless Chromium took
16.25 CPU-seconds every 15 seconds for its 26 never-ending animations, and 0.52 with them paused; Thomas's tests and
checks keep several such pages open at once. The script at the top of thomas/server/web/chat.html pauses only
animations that never end, so a fade still reaches its end and the page looks as it would after it, and
``?motion=1`` keeps every animation running. These tests run that exact script in a real browser.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CHAT = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "chat.html"


def _script() -> str:
    html = CHAT.read_text(encoding="utf-8")
    found = re.search(r"<script>\(function\(\)\{try\{if\(!navigator\.webdriver.*?</script>", html)
    assert found, "chat.html lost the script that pauses endless animations in a program-driven browser"
    assert html.index(found.group(0)) < html.index('<link rel="stylesheet"'), "it must run before any stylesheet"
    return found.group(0)


PAGE = """<!doctype html><html><head>{script}<style>
@keyframes spin {{ to {{ transform: rotate(360deg) }} }}
@keyframes appear {{ from {{ opacity: 0 }} to {{ opacity: 1 }} }}
#stars {{ animation: spin 2s linear infinite }}
#notice {{ opacity: 0; animation: appear .3s ease-out forwards }}
</style></head><body><div id="stars">*</div><div id="notice">Saved</div></body></html>"""

STATE = """() => {
  const of = (id) => document.getElementById(id).getAnimations()[0];
  return {
    marked: document.documentElement.hasAttribute('data-automated'),
    stars: of('stars').playState,
    notice: of('notice') ? of('notice').playState : 'finished',
    noticeOpacity: getComputedStyle(document.getElementById('notice')).opacity,
  };
}"""


def _state(query: str) -> dict:
    sync_api = pytest.importorskip("playwright.sync_api")
    body = PAGE.format(script=_script())
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 - no browser installed on this machine
            pytest.skip(f"Chromium is not available: {exc}")
        try:
            page = browser.new_page()
            page.route("http://motion.test/**", lambda route: route.fulfill(body=body, content_type="text/html"))
            page.goto(f"http://motion.test/{query}", wait_until="load")
            page.wait_for_timeout(700)
            return page.evaluate(STATE)
        finally:
            browser.close()


def test_endless_animations_pause_and_ending_ones_still_finish() -> None:
    state = _state("")
    assert state["marked"] is True
    assert state["stars"] == "paused", "a never-ending animation kept running in a program-driven browser"
    assert state["notice"] == "finished" and state["noticeOpacity"] == "1", "an animation that ends must still end"


def test_motion_1_keeps_every_animation_running() -> None:
    state = _state("?motion=1")
    assert state["marked"] is False
    assert state["stars"] == "running"
