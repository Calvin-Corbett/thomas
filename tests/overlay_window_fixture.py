"""What the overlay row's window tests share: the saved changes, a real window, and the things done in it.

Helpers return data and the tests assert, because pytest rewrites asserts only in a test module.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

WINDOW = {"width": 1366, "height": 768}
ANCHOR = {
    "exact": True,
    "fragile": False,
    "component": "aside",
    "label": "Chat sidebar",
    "policy": "move resize",
    "path": "",
}
EMBER = {
    "label": "Ember",
    "tagline": "Warm dark",
    "derives_from": "nebula",
    "color_scheme": "dark",
    "swatches": ["#140a06", "#2a1408", "#ff7a1a"],
    "world": "nebula",
    "meta": {"menuBg": "#1c0f08"},
}
SAVED = [
    {"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#2ecc71"},
    {"op": "set", "kind": "identity", "address": "identity:name", "value": "Otto"},
    {
        "op": "set",
        "kind": "element",
        "address": "element:chat:desktop:chat.sidebar",
        "value": {"x": 0, "y": 0, "width": 320, "style": {"backgroundColor": "#101a2e"}},
        "anchor": ANCHOR,
    },
    {"op": "set", "kind": "theme", "address": "theme:ember", "value": EMBER},
    {"op": "set", "kind": "token", "address": "token:ember:--c-bg", "value": "#140a06"},
]
# Redesign's own reply is canned, because what is tested is what happens to it. It asks for the sidebar, a colour and a name.
CANNED = {
    "ok": True,
    "layout": [{"target_index": 0, "ui_id": "chat.sidebar", "style": {"backgroundColor": "#552200"}, "width": 400}],
    "dashboard": {"changed": 0, "applied": []},
    "theme": {"theme": "nebula", "tokens": {"--c-accent": "#ff0066"}, "identity": {"name": "Ada"}, "rejected": []},
    "unsupported": [],
    "code_thread": None,
}
PAGES = ("/", "/classic", "/settings", "/companion", "/mission")
# Seconds. The Marketplace page asked 28 times a second with its row off, so a page that loops shows in a few.
WATCHED = 10
# After the first five seconds a page has loaded. The most any of these asks in the next five, with the row on, is far below.
SETTLED_MOST = 40
STATE = """() => {
  const side = document.querySelector('[data-ui-id="chat.sidebar"]');
  const input = document.getElementById('tc-input');
  return {
    accent: getComputedStyle(document.getElementById('tc-shell')).getPropertyValue('--c-accent').trim(),
    sidebar: side ? getComputedStyle(side).backgroundColor : null,
    width: side ? side.style.width : null,
    asks: input ? input.placeholder : null,
    theme: document.documentElement.dataset.theme,
    bg: getComputedStyle(document.documentElement).getPropertyValue('--c-bg').trim(),
    runtime: typeof window.ThomasOverlay,
    chosen: localStorage.getItem('thomas_chat_theme'),
    knows_ember: !!(window.ThomasChatThemes && window.ThomasChatThemes.THEMES && window.ThomasChatThemes.THEMES.ember),
  };
}"""
ON_LOOKS = {"accent": "#2ecc71", "sidebar": "rgb(16, 26, 46)", "width": "320px", "runtime": "object"}
# As Thomas ships, Chat wears the one Dark it shares with Build and Work (2026-11-10: "Flat like Build"), not the stock
# theme: the accent was #8b8cff and the sidebar rgba(11, 14, 26, 0.72) while Chat followed Nebula.
STOCK_LOOKS = {"accent": "#6e9bff", "sidebar": "rgb(16, 18, 22)", "width": "280px", "runtime": "undefined"}


def ask(base: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, str]:
    request = urllib.request.Request(
        base + path,
        method="GET" if body is None else "POST",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:
            return answer.status, answer.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as refused:
        return refused.code, refused.read().decode("utf-8", "replace")


def press(base: str, how: str) -> None:
    status, body = ask(base, f"/api/plugins/thomas/overlay/{how}", {})
    if status != 200:
        raise RuntimeError(f"the switch answered {status}: {body}")
    time.sleep(1.5)  # a request in the moment before the choice is saved can still reach the route


def home(browser: Any, base: str, *, canned: bool = False, context: Any = None) -> Any:
    """Open Chat in a window. Pass ``context`` to share a browser's saved choices, such as a theme, with another window."""
    page = (context or browser.new_context(viewport=WINDOW)).new_page()
    page.set_default_timeout(60_000)
    if canned:
        page.route(
            "**/api/ui/redesign",
            lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(CANNED)),
        )
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("#tc-shell")
    page.wait_for_timeout(1500)
    return page


def redesign_note(page: Any) -> str:
    """Do what you do to Redesign with AI: open it from the plus menu, pick the sidebar, say what you want, and Apply."""
    page.click("#tc-attach-btn")
    page.click("[data-create-action=redesign]")
    page.wait_for_function("() => window.ThomasRedesign.phase() === 'selecting'")
    page.evaluate("() => document.querySelector('[data-ui-id=\"chat.sidebar\"]').click()")
    page.wait_for_function("() => window.ThomasRedesign.selection().length === 1")
    page.click('[data-tr="lock"]')
    page.fill(".tr-input", "make the sidebar wider and the accent pink, and call yourself Ada")
    page.click('[data-tr="apply"]')
    page.wait_for_selector(".tr-result")
    return page.inner_text(".tr-result")


def watch(browser: Any, base: str, path: str) -> dict[str, int]:
    """Open a page in a window of its own and count what it asks for: in all, in the last five seconds, and for the routes."""
    context = browser.new_context(viewport=WINDOW)
    page = context.new_page()
    asked: Counter[str] = Counter()
    page.on("request", lambda request: asked.update([urlsplit(request.url).path]))
    page.goto(base + path, wait_until="domcontentloaded")
    page.wait_for_timeout(WATCHED * 500)
    asked.clear()
    page.wait_for_timeout(WATCHED * 500)
    found = {
        "settled": sum(asked.values()),
        "routes": sum(count for path_, count in asked.items() if path_.startswith("/api/ui/overlay")),
    }
    context.close()
    return found


SHOWN_FRAMES = """() => {
  const shown = Array.from(document.querySelectorAll('iframe')).filter((f) => f.getClientRects().length > 0);
  const loaded = (f) => f.contentDocument && f.contentDocument.readyState === 'complete'
    && f.contentWindow.location.pathname === f.getAttribute('src').split('?')[0];
  if (!shown.length || !shown.every(loaded)) return null;
  return shown.map((f) => [f.getAttribute('src').split('?')[0], !!f.contentDocument.getElementById('thomas-overlay-view')]);
}"""


def open_from(page: Any, button: str) -> list[list[Any]]:
    """Press a button that opens a page in a frame, wait for the frame to load, and say which page and whether it carries the view."""
    page.click(button)
    page.wait_for_function(SHOWN_FRAMES)
    return page.evaluate(SHOWN_FRAMES)


def in_the_sidebar(page: Any, names: tuple[str, ...]) -> dict[str, list[list[Any]]]:
    return {name: open_from(page, f"button:has-text('{name}')") for name in names}


def redesign_menu(page: Any) -> dict[str, Any]:
    page.click("#tc-attach-btn")
    item = page.locator("[data-create-action=redesign]")
    item.wait_for(state="visible")
    found = {"words": item.inner_text().strip(), "title": page.locator("#tc-attach-btn").get_attribute("aria-label")}
    item.click()
    page.wait_for_function("() => window.ThomasRedesign.phase() === 'selecting'")
    found["phase"] = page.evaluate("() => window.ThomasRedesign.phase()")
    page.evaluate("() => window.ThomasRedesign.cancel && window.ThomasRedesign.cancel()")
    return found


def reload(page: Any) -> dict[str, Any]:
    page.reload()
    page.wait_for_selector("#tc-shell")
    page.wait_for_timeout(1500)
    return page.evaluate(STATE)


def watch_open(page: Any) -> dict[str, int]:
    """The page that was open when the row went off, left alone, and counted."""
    asked: Counter[str] = Counter()
    page.on("request", lambda request: asked.update([urlsplit(request.url).path]))
    page.wait_for_timeout(WATCHED * 1000)
    return {
        "settled": sum(asked.values()),
        "routes": sum(count for path, count in asked.items() if path.startswith("/api/ui/overlay")),
    }


def looks(state: dict[str, Any], expected: dict[str, str]) -> dict[str, Any]:
    return {key: state[key] for key in expected}
