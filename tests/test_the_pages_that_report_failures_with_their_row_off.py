"""Chat, Code and Work with the issues row off, read from a real window on a real server.

``chat_message_view.js``, ``unified_code_mode.js`` and ``unified_work_mode.js`` post a note to ``/api/issues`` when
something goes wrong, and never wait for the answer. With the row off that post gets 404, which is not a failure to
``fetch``, so nothing is raised and nothing is sent again. These count the posts over ten seconds in each page and for a
failure made on purpose in Chat.

Proofs of ``thomas.server.rows.issues`` and ``thomas.server.routes.issues_aiohttp``, for the words in
``tests/test_turning_issues_off_touches_only_its_routes.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.row_page_fixture import serving
from tests.web_fixtures.thomas_chat_fixture import browser_ok

TEN_SECONDS = 10_000
LOOPING = 20
PAGES = {"chat": None, "code": "button[data-thomas-mode='code']", "work": "button[data-thomas-mode='work']"}


def _walk(base: str, browser: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for name, button in PAGES.items():
        context = browser.new_context(viewport={"width": 1500, "height": 950})
        asked: list[str] = []
        answered: list[int] = []
        context.on("request", lambda r, asked=asked: asked.append(r.method) if r.url.endswith("/api/issues") else None)
        context.on(
            "response",
            lambda r, answered=answered: answered.append(r.status) if r.url.endswith("/api/issues") else None,
        )
        page = context.new_page()
        page.set_default_timeout(60_000)
        errors: list[str] = []
        page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
        page.goto(base, wait_until="domcontentloaded")
        page.evaluate("async () => (await fetch('/api/plugins/thomas/issues/off', { method: 'POST' })).status")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("button[data-thomas-mode='chat']", timeout=90_000)
        if button:
            page.click(button)
        asked.clear()
        answered.clear()
        page.wait_for_timeout(TEN_SECONDS)
        # Code and Work open in a window of their own inside the page, named by tab_mode in its address.
        window = next((f for f in page.frames if f"tab_mode={name}" in f.url), page.main_frame)
        seen[name] = {
            "posts_at_rest": len(asked),
            "on_screen": " ".join(window.evaluate("document.body.innerText").split()),
            "mode": name if window is not page.main_frame or name == "chat" else None,
        }
        if name == "chat":
            asked.clear()
            answered.clear()
            page.evaluate("() => { Promise.reject(new Error('made on purpose by the test')); }")
            page.wait_for_timeout(TEN_SECONDS)
            seen[name].update(posts_after_a_failure=len(asked), answers=list(answered), page_errors=errors)
        context.close()
    return seen


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    folder: Path = tmp_path_factory.mktemp("issues-pages")
    with serving(folder) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            return _walk(base, browser)
        finally:
            browser.close()


def test_the_pages_open_and_go_on_working(seen: dict[str, Any]) -> None:
    assert {name: found["mode"] for name, found in seen.items()} == {"chat": "chat", "code": "code", "work": "work"}
    assert all(len(found["on_screen"]) > 50 for found in seen.values()), seen


def test_a_page_does_not_send_it_again_and_again(seen: dict[str, Any]) -> None:
    assert all(found["posts_at_rest"] < LOOPING for found in seen.values()), seen
    assert seen["chat"]["posts_after_a_failure"] < LOOPING, seen["chat"]


def test_a_note_a_page_sends_gets_404_and_nothing_on_the_screen_says_so(seen: dict[str, Any]) -> None:
    chat = seen["chat"]
    assert chat["posts_after_a_failure"] >= 1, chat
    assert set(chat["answers"]) == {404}, chat
    assert "404" not in chat["on_screen"], chat["on_screen"]
