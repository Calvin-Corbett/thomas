"""The Marketplace page in a real browser: where things are on it, and one walk through it with the row on, off and on.

``tests/test_the_marketplace_page_when_its_row_is_off.py`` reads what this walk saw. The row is
``thomas.server.rows.catalog``, and the page's code is ``036_workbench_editors_08.js``,
``025_module_system_command_center_01.js`` and ``marketplace_kernel.js``.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

# A common laptop window. Taller ones show a little more of the same page, and only a very tall one, such as 2560 by
# 1440, reaches the words at the bottom of it.
WINDOW = {"width": 1366, "height": 768}
OVER_THE_PAGE = (800, 500)
SIDEBAR = "#tc-workspaces"
# This mark comes when the tabs are ready for it. A press before that opens a frame that the tabs then take away.
SIDEBAR_BUTTON = f"{SIDEBAR} button[data-bt-mode='marketplace']"
PAGE_FRAME = "iframe[src*='/classic']"
HEAD = ".marketplace-sticky-head"
THE_LIST = ".marketplace-card-grid"
CARD = ".marketplace-product-card"
UNAVAILABLE = ".marketplace-empty-state-error"
PLUGGED_IN = ".marketplace-kernel"
FROM_A_LINK = "[data-marketplace-import-url]"
SEARCH = "[data-module-marketplace-search]"
TYPED = "inkwell"
REFRESH = "[data-module-marketplace-refresh]"
SYNC = "/api/marketplace/sync"
# Milliseconds. Longer than the 15 seconds between the page's own redraws, so one of them falls inside it and could ask.
WAITS_THROUGH = 20_000
# Milliseconds. The 75 second wait after a failed ask, then up to 15 more for the next redraw to ask, and some to spare.
BACK_WITHIN = 110_000
ASKED_AND_FAILED = "() => { const it = moduleEnsureRuntime().marketplace; return !it.loading && !it.refreshSucceeded; }"
FILLED_IN = "() => moduleEnsureRuntime().marketplace.refreshSucceeded === true"
# All the page says of itself with the row off, written out, because the row's words were checked against this.
HEAD_OFF = (
    "Install From File Install from URL Sync Catalog Marketplace unavailable. "
    "Marketplace and installed apps is turned off, or could not start. To turn it on, go to Settings, then Plugins. "
    "Thomas tries again about every minute and a half, or press Sync Catalog to try now."
)


def words(frame: Any, selector: str) -> str:
    return " ".join(frame.evaluate("(selector) => document.querySelector(selector).innerText", selector).split())


def sidebar(page: Any) -> list[str]:
    # The name is the row's first span. The whole row's text also carries its "⋯" menu control, added 2026-11-09.
    name = "(button) => (button.querySelector('span') || button).innerText.trim()"
    return page.eval_on_selector_all(f"{SIDEBAR} button", f"(all) => all.map({name})")


def library(page: Any) -> str:
    page.click(f"{SIDEBAR} button:has-text('Library')")
    frame = page.wait_for_selector("iframe[src*='/my-stuff']").content_frame()
    frame.wait_for_function("() => document.body.innerText.includes('loaded.')")
    return " ".join(frame.evaluate("() => document.body.innerText").split())


def marketplace_loaded(page: Any) -> Any:
    frame = page.wait_for_selector(PAGE_FRAME).content_frame()
    frame.wait_for_selector(HEAD)
    # A server with no model opens its first-run dialog over the page. You would close it, and it is not this row's.
    frame.evaluate(
        "() => ['easySetupModal', 'easySetupBackdrop'].forEach((id) => document.getElementById(id)?.remove())"
    )
    return frame


def open_marketplace(page: Any) -> Any:
    page.click(SIDEBAR_BUTTON)
    return marketplace_loaded(page)


def wheeled(page: Any, frame: Any) -> int:
    """How many things moved when the wheel turned over the page."""
    page.mouse.move(*OVER_THE_PAGE)
    for _ in range(4):
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(100)
    return frame.evaluate("() => [...document.querySelectorAll('*')].filter((node) => node.scrollTop > 0).length")


def centre(page: Any, frame: Any, selector: str) -> tuple[float, float]:
    """Where on the screen a thing is, read in one go, because on a page that redraws it may be gone by the next call."""
    box = page.query_selector(PAGE_FRAME).bounding_box()
    x, y = frame.evaluate(
        """(selector) => {
            const { left, top, width, height } = document.querySelector(selector).getBoundingClientRect();
            return [left + width / 2, top + height / 2];
        }""",
        selector,
    )
    return box["x"] + x, box["y"] + y


def just_after_a_redraw(frame: Any) -> None:
    """The page redraws every 15 seconds with the row on or off, and a box that is redrawn loses your cursor."""
    frame.wait_for_function("(node) => !node.isConnected", arg=frame.query_selector(".marketplace-surface"))


def walk(base: str, browser: Any) -> dict[str, Any]:
    """Row on, then off with two pages open, then each page reloaded, then on again, as you would meet them."""
    seen: dict[str, Any] = {}
    context = browser.new_context(viewport=WINDOW)
    asked: Counter[str] = Counter()
    context.on("request", lambda request: asked.update([urlsplit(request.url).path]))
    sent: list[float] = []  # when each ask for the list went out
    context.on("request", lambda request: sent.append(time.monotonic()) if urlsplit(request.url).path == SYNC else None)
    page = context.new_page()
    page.set_default_timeout(60_000)
    prompts: list[str] = []
    page.on("dialog", lambda dialog: (prompts.append(dialog.message), dialog.dismiss()))

    def asks_after_failing_just_now(leave: bool = False) -> int:
        market.click(REFRESH)
        market.wait_for_function(ASKED_AND_FAILED)
        seen["last_failed"] = time.monotonic()
        if leave:
            page.click(".bt-tab:has-text('Chat')")
        asked.clear()
        page.wait_for_timeout(WAITS_THROUGH)
        return asked[SYNC]

    def answer_of(url: str, tab: Any) -> tuple[int, str]:
        status = tab.goto(url, wait_until="domcontentloaded").status
        return status, tab.evaluate("() => document.body.innerText").strip()

    # On: everything the words say goes away is there first, so nothing below can be a page that never worked.
    seen["install"] = context.request.post(f"{base}/api/marketplace/plugins/inkwell/install", data={}).status
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector(f"{SIDEBAR} button:has-text('Inkwell')")
    seen["sidebar_on"] = sidebar(page)
    seen["library_on"] = library(page)
    market = open_marketplace(page)
    market.wait_for_selector(CARD)
    seen["cards_on"] = market.locator(CARD).count()
    page.mouse.click(*centre(page, market, FROM_A_LINK), delay=120)
    page.wait_for_timeout(300)
    seen["prompts_on"] = len(prompts)
    prompts.clear()
    seen["scrolled_on"] = wheeled(page, market)
    app = context.new_page()
    app.set_default_timeout(60_000)
    app.goto(f"{base}/app/inkwell", wait_until="domcontentloaded")
    app.wait_for_selector("#micBtn")

    # Off, with both pages still open.
    pressed = context.request.post(f"{base}/api/plugins/thomas/catalog/off", data={})
    seen["pressed_off"] = pressed.status
    seen["off_means"] = pressed.json()["off_means"]
    seen["note_from_the_open_app"] = app.evaluate(
        """async () => (await fetch('/api/plugins/inkwell/notes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: 'Written while the row was off.' }),
        })).status"""
    )
    page.bring_to_front()
    market.click(REFRESH)
    market.wait_for_function("() => moduleEnsureRuntime().marketplace.refreshSucceeded === false")
    seen["cards_open"] = market.locator(CARD).count()
    seen["words_open"] = words(market, UNAVAILABLE)
    seen["install_from_it"] = market.evaluate("() => moduleInstallMarketplacePlugin('inkwell')")
    seen["remove_from_it"] = market.evaluate("() => moduleUninstallMarketplacePlugin('inkwell')")
    seen["open_app_reloaded"] = answer_of(app.url, app)
    seen["shortcut"] = answer_of(f"{base}/app/inkwell", app)
    app.close()

    # A new window, which is what you get when you open Thomas again. The sidebar belongs to the window.
    window = context.new_page()
    window.set_default_timeout(60_000)
    with window.expect_response(lambda answer: urlsplit(answer.url).path == "/api/marketplace/installed"):
        window.goto(base, wait_until="domcontentloaded")
    window.wait_for_selector(f"{SIDEBAR} button:has-text('Marketplace')")
    window.wait_for_timeout(1000)
    seen["sidebar_off"] = sidebar(window)
    seen["library_off"] = library(window)
    window.close()

    # The reload button, which Ctrl+R and F5 press too. It reloads this tab and leaves the window alone.
    page.bring_to_front()
    page.click("#bt-reload")
    page.wait_for_timeout(1000)
    market = marketplace_loaded(page)
    market.wait_for_selector(UNAVAILABLE)
    seen["head_off"] = words(market, HEAD)
    seen["list_off"] = words(market, THE_LIST)
    seen["plugged_in_off"] = words(market, PLUGGED_IN)
    seen["cards_off"] = market.locator(CARD).count()
    seen["words_top"], seen["words_bottom"], seen["window_height"] = market.evaluate(
        """(selector) => {
            const { top, bottom } = document.querySelector(selector).getBoundingClientRect();
            return [top, bottom, innerHeight];
        }""",
        UNAVAILABLE,
    )
    seen["kernel_sync"] = context.request.post(f"{base}/api/plugins/kernel/sync", data={}).status
    seen["asked_on_the_page"] = asks_after_failing_just_now()
    just_after_a_redraw(market)
    page.mouse.click(*centre(page, market, FROM_A_LINK), delay=120)
    page.wait_for_timeout(300)
    seen["prompts_off"] = len(prompts)
    page.mouse.click(*centre(page, market, SEARCH))
    page.keyboard.type(TYPED, delay=150)
    seen["typed"] = market.evaluate("(selector) => document.querySelector(selector).value", SEARCH)
    seen["scrolled_off"] = wheeled(page, market)

    # Left, and on again from there, and the page is left to find that out for itself. A hidden frame draws no frames.
    seen["asked_from_another_tab"] = asks_after_failing_just_now(leave=True)
    seen["pressed_on"] = context.request.post(f"{base}/api/plugins/thomas/catalog/on", data={}).status
    market.wait_for_function(FILLED_IN, timeout=BACK_WITHIN, polling=1000)
    seen["asked_again_after"] = min(at for at in sent if at > seen["last_failed"]) - seen["last_failed"]
    page.click(".bt-tab:has-text('Marketplace')")
    market.wait_for_selector(CARD)
    seen["apps_back"] = market.evaluate("() => moduleEnsureRuntime().marketplace.apps.length")
    seen["words_after_on"] = market.locator(UNAVAILABLE).count()

    # Off and on once more, and this time you do not wait for it.
    context.request.post(f"{base}/api/plugins/thomas/catalog/off", data={})
    market.click(REFRESH)
    market.wait_for_function("() => moduleEnsureRuntime().marketplace.refreshSucceeded === false")
    context.request.post(f"{base}/api/plugins/thomas/catalog/on", data={})
    pressed = time.monotonic()
    market.click(REFRESH)
    market.wait_for_function(FILLED_IN, timeout=BACK_WITHIN)
    seen["back_after_a_press_in"] = time.monotonic() - pressed
    return seen
