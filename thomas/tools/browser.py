# thomas/tools/browser.py
"""
Browser automation tools for Thomas using Playwright (async API).

TOOLS:
- browser.open        : navigate to URL, return title + cleaned page text (max 8000 chars)
- browser.click       : click an element on the current page
- browser.type        : type text into an input on the current page
- browser.screenshot  : take screenshot of current page
- browser.extract     : extract structured strings from page
- browser.close       : close the browser + cleanup Playwright

Meaningful "consumer-grade" upgrades (v5):
1) Human-friendly selectors (optional, automatic fallback)
   - If a selector doesn't look like CSS/XPath, we treat it as a *human label* and try:
     - click: get_by_role(button/link) -> get_by_text
     - type:  get_by_label -> get_by_placeholder -> CSS/XPath fallback
   This lets callers say "Sign in" or "Email" instead of fighting CSS.

2) Multi-session support (still one shared Browser)
   - Optional `session` param across tools (default: "default").
   - Each session has its own BrowserContext + Page (cookies/login isolated).
   - "Current page" becomes "current page for that session".
   - Consumers love this because automations can run without clobbering each other.

3) Better text extraction
   - Picks the best content container using a simple readability-style scoring:
     text length penalized by link density, after stripping nav/header/footer/aside + cookie banners.
   - Returns cleaner "article-like" text, still capped at 8000 chars.

4) Resilience + ergonomics
   - Self-heals closed/crashed pages automatically.
   - Remembers last good URL per session and can rehydrate on demand for click/type/extract/screenshot.
   - Click does a short stabilize after clicking (handles SPA route changes & navigations).

Install:
- pip install playwright
- playwright install chromium
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from typing import Any

# --- Thomas types ---
try:
    from thomas.tools.base import Tool, ToolResult  # type: ignore
except Exception:  # pragma: no cover
    try:
        from thomas.tools.tool import Tool, ToolResult  # type: ignore
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "Could not import Tool/ToolResult. Expected thomas.tools.base or thomas.tools.tool."
        ) from e

from thomas.tools.browser_content import (
    _clean_text,
    _extract_best_text,
    _read_page_headline,
    _same_target_url,
)
from thomas.tools.browser_helpers import (
    _best_effort_read_stabilize,
    _best_effort_stabilize,
    _ensure_navigated,
    _fmt_action_error,
    _fmt_nav_error,
    _navigate_via_locator_href,
    _normalize_selector,
    _normalize_url,
    _resolve_locator_for_click,
    _resolve_locator_for_type,
    _resolve_screenshot_path,
)
from thomas.tools.browser_sessions import (
    _ACTION_BROWSER_LANE,
    _BROWSER_STATES,
    _READ_BROWSER_LANE,
    _ensure_session_page,
    _get_session_name,
    _rehydrate_if_needed,
    _state_for_lane,
    shutdown_browser,
    warm_browser_session,  # noqa: F401 - re-exported for chat route warm-up compatibility
)

# --- Playwright ---
_PLAYWRIGHT_AVAILABLE = True
_PLAYWRIGHT_IMPORT_ERROR: str | None = None
try:
    from playwright.async_api import (
        Error as PlaywrightError,
    )
except Exception as e:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False
    _PLAYWRIGHT_IMPORT_ERROR = str(e)


# ----------------------------
# Constants
# ----------------------------

_NAV_TIMEOUT_MS = 30_000
_ACTION_TIMEOUT_MS = 5_000
_EXTRACT_MAX_ITEMS = 200
_PREFERRED_BROWSER_EXECUTABLES = (
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
)



# ----------------------------
# Helper utilities
# ----------------------------

def _browser_launch_kwargs(headless: bool) -> dict[str, Any]:
    override = os.environ.get("THOMAS_BROWSER_EXECUTABLE", "").strip()
    candidates = ([override] if override else []) + list(_PREFERRED_BROWSER_EXECUTABLES)
    for raw in candidates:
        candidate = Path(str(raw or "").strip())
        if not candidate:
            continue
        if candidate.exists():
            return {"headless": headless, "executable_path": str(candidate)}
    return {"headless": headless}


def _browser_context_kwargs() -> dict[str, Any]:
    return {"ignore_https_errors": True}


# ----------------------------
# Tools
# ----------------------------

class BrowserOpenTool(Tool):
    name = "browser.open"
    category = "browser"
    description = "Navigate to a URL and return page title + cleaned text (max 8000 chars)."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to navigate to."},
            "wait_for": {"type": "string", "description": "Optional CSS selector to wait for."},
            "headless": {"type": "boolean", "description": "Run headless (default true).", "default": True},
            "lane": {
                "type": "string",
                "description": "Optional internal browser lane override ('read' or 'action').",
            },
            "headline_only": {
                "type": "boolean",
                "description": "Return headline/title only and skip heavier page text extraction when possible.",
                "default": False,
            },
            "navigation_only": {
                "type": "boolean",
                "description": "Optional internal fast path: navigate only and skip page metadata extraction.",
                "default": False,
            },
            "session": {"type": "string", "description": "Optional session name (isolated cookies). Default 'default'."},
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            raw_url = (args.get("url") or "").strip()
            if not raw_url:
                return ToolResult(ok=False, data=None, error="Missing required param: url")

            url = _normalize_url(raw_url)
            wait_for = (args.get("wait_for") or "").strip() or None
            headless = bool(args.get("headless", True))
            headline_only = bool(args.get("headline_only", False))
            navigation_only = bool(args.get("navigation_only", False))
            requested_lane = str(args.get("lane") or "").strip().lower()
            lane = requested_lane if requested_lane in {_READ_BROWSER_LANE, _ACTION_BROWSER_LANE} else (
                _READ_BROWSER_LANE if headline_only else _ACTION_BROWSER_LANE
            )
            state = _state_for_lane(lane)
            session_name = _get_session_name(args, lane=lane)

            sess, page = await _ensure_session_page(session_name, headless=headless, lane=lane)

            async with sess.lock:
                try:
                    current_url = ""
                    with suppress(Exception):
                        current_url = page.url or ""
                    resp = None
                    if not _same_target_url(current_url, url):
                        nav_wait_until = "commit" if headline_only or lane == _READ_BROWSER_LANE else "domcontentloaded"
                        resp = await page.goto(url, wait_until=nav_wait_until, timeout=_NAV_TIMEOUT_MS)
                except Exception as e:
                    return ToolResult(ok=False, data=None, error=_fmt_nav_error(url, e, _NAV_TIMEOUT_MS))

                if resp is not None:
                    with suppress(Exception):
                        status = resp.status
                        if status >= 400:
                            return ToolResult(ok=False, data=None, error=f"HTTP {status} while navigating to {url}")

                if wait_for:
                    try:
                        await page.wait_for_selector(_normalize_selector(wait_for), timeout=_NAV_TIMEOUT_MS, state="attached")
                    except Exception as e:
                        return ToolResult(ok=False, data=None, error=_fmt_action_error("Wait for selector", e, wait_for))

                if navigation_only:
                    with suppress(Exception):
                        sess.last_url = page.url
                    if sess.last_url is None:
                        sess.last_url = url
                    state.active_session = session_name
                    current_url = ""
                    with suppress(Exception):
                        current_url = page.url or ""
                    if not current_url:
                        current_url = url
                    return ToolResult(
                        ok=True,
                        data={"url": current_url or url, "title": "", "headline": "", "text": ""},
                        error=None,
                    )

                try:
                    title = await page.title()
                except Exception:
                    title = ""

                if headline_only:
                    if wait_for:
                        with suppress(Exception):
                            await page.wait_for_timeout(150)
                    else:
                        with suppress(Exception):
                            await page.wait_for_selector("h1", timeout=1200, state="attached")
                        with suppress(Exception):
                            await page.wait_for_load_state("domcontentloaded", timeout=1500)
                    headline = await _read_page_headline(page, title)
                    text = ""
                else:
                    if lane == _READ_BROWSER_LANE:
                        with suppress(Exception):
                            await page.wait_for_load_state("domcontentloaded", timeout=1500)
                        await _best_effort_read_stabilize(page, settle_ms=200)
                    else:
                        await _best_effort_stabilize(page, max_ms=5000)
                    headline = await _read_page_headline(page, title)
                    text = _clean_text(await _extract_best_text(page))

                # Remember last good URL for rehydration
                try:
                    sess.last_url = page.url
                except Exception:
                    sess.last_url = url

                state.active_session = session_name

                return ToolResult(
                    ok=True,
                    data={"url": page.url, "title": title, "headline": headline, "text": text},
                    error=None,
                )

        except RuntimeError as e:
            return ToolResult(ok=False, data=None, error=str(e))
        except Exception as e:
            return ToolResult(ok=False, data=None, error=f"browser.open failed: {e}")


class BrowserClickTool(Tool):
    name = "browser.click"
    category = "browser"
    description = "Click an element on the current page (CSS/XPath) or by human label (e.g., 'Sign in')."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS or XPath selector (or human label as fallback)."},
            "timeout_ms": {"type": "integer", "description": "Timeout in ms (default 5000).", "default": 5000},
            "post_click_stabilize_ms": {
                "type": "integer",
                "description": "Optional internal post-click stabilization budget in ms.",
                "default": 3000,
            },
            "prefer_link_navigation": {
                "type": "boolean",
                "description": "Optional internal fast path: navigate directly when the resolved element is a simple link.",
                "default": False,
            },
            "session": {"type": "string", "description": "Optional session name. Default is current active session."},
        },
        "required": ["selector"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            selector_in = (args.get("selector") or "").strip()
            if not selector_in:
                return ToolResult(ok=False, data=None, error="Missing required param: selector")

            timeout_ms = int(args.get("timeout_ms", _ACTION_TIMEOUT_MS))
            if timeout_ms <= 0:
                timeout_ms = _ACTION_TIMEOUT_MS
            post_click_stabilize_ms = int(args.get("post_click_stabilize_ms", 3000))
            if post_click_stabilize_ms < 0:
                post_click_stabilize_ms = 3000
            prefer_link_navigation = bool(args.get("prefer_link_navigation", False))

            lane = _ACTION_BROWSER_LANE
            state = _state_for_lane(lane)
            session_name = _get_session_name(args, lane=lane)
            sess, page = await _ensure_session_page(session_name, lane=lane)

            async with sess.lock:
                reh_err = await _rehydrate_if_needed(sess, page)
                if reh_err:
                    return ToolResult(ok=False, data=None, error=reh_err)

                nav_err = _ensure_navigated(page)
                if nav_err:
                    return ToolResult(ok=False, data=None, error=nav_err)

                before_url = ""
                with suppress(Exception):
                    before_url = page.url or ""

                try:
                    loc = await _resolve_locator_for_click(page, selector_in)
                    await loc.wait_for(state="attached", timeout=timeout_ms)
                    navigated_directly = False
                    if prefer_link_navigation:
                        navigated_directly = await _navigate_via_locator_href(page, loc, timeout_ms=timeout_ms)
                    if not navigated_directly:
                        await loc.scroll_into_view_if_needed(timeout=timeout_ms)
                        await loc.wait_for(state="visible", timeout=timeout_ms)
                        await loc.click(timeout=timeout_ms)
                except Exception as e:
                    # Fallback forced click if we were using CSS/XPath/engine locator; for human locators it still may help
                    try:
                        loc = await _resolve_locator_for_click(page, selector_in)
                        await loc.click(timeout=timeout_ms, force=True)
                    except Exception:
                        return ToolResult(ok=False, data=None, error=_fmt_action_error("Click", e, selector_in))

                stabilize_budget_ms = post_click_stabilize_ms
                if prefer_link_navigation and navigated_directly:
                    with suppress(Exception):
                        await page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 600))
                    stabilize_budget_ms = min(post_click_stabilize_ms, 250)

                await _best_effort_stabilize(page, max_ms=stabilize_budget_ms)

                # Track URL changes
                try:
                    after_url = page.url or ""
                    if after_url and after_url != "about:blank":
                        sess.last_url = after_url
                except Exception:
                    pass

                state.active_session = session_name

                changed = False
                try:
                    changed = bool(before_url and page.url and page.url != before_url)
                except Exception:
                    changed = False

                return ToolResult(ok=True, data={"clicked": selector_in, "url_changed": changed}, error=None)

        except RuntimeError as e:
            return ToolResult(ok=False, data=None, error=str(e))
        except Exception as e:
            return ToolResult(ok=False, data=None, error=f"browser.click failed: {e}")


class BrowserTypeTool(Tool):
    name = "browser.type"
    category = "browser"
    description = "Type text into an input (CSS/XPath) or by human label (e.g., 'Email')."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS/XPath selector (or human label as fallback)."},
            "text": {"type": "string", "description": "Text to type."},
            "clear_first": {"type": "boolean", "description": "Clear first (default true).", "default": True},
            "session": {"type": "string", "description": "Optional session name. Default is current active session."},
        },
        "required": ["selector", "text"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            selector_in = (args.get("selector") or "").strip()
            if not selector_in:
                return ToolResult(ok=False, data=None, error="Missing required param: selector")
            if "text" not in args:
                return ToolResult(ok=False, data=None, error="Missing required param: text")
            text = str(args.get("text", ""))

            clear_first = bool(args.get("clear_first", True))
            lane = _ACTION_BROWSER_LANE
            state = _state_for_lane(lane)
            session_name = _get_session_name(args, lane=lane)
            sess, page = await _ensure_session_page(session_name, lane=lane)

            async with sess.lock:
                reh_err = await _rehydrate_if_needed(sess, page)
                if reh_err:
                    return ToolResult(ok=False, data=None, error=reh_err)

                nav_err = _ensure_navigated(page)
                if nav_err:
                    return ToolResult(ok=False, data=None, error=nav_err)

                try:
                    loc = await _resolve_locator_for_type(page, selector_in)
                    await loc.wait_for(state="attached", timeout=_ACTION_TIMEOUT_MS)
                    await loc.scroll_into_view_if_needed(timeout=_ACTION_TIMEOUT_MS)
                    await loc.wait_for(state="visible", timeout=_ACTION_TIMEOUT_MS)
                    await loc.click(timeout=_ACTION_TIMEOUT_MS)

                    if clear_first:
                        # fill() clears and sets value; best for inputs/textareas
                        try:
                            await loc.fill(text, timeout=_ACTION_TIMEOUT_MS)
                        except PlaywrightError:
                            # Fallback for custom widgets/contenteditable
                            await loc.press("Control+A")
                            await loc.press("Backspace")
                            await loc.type(text, timeout=_ACTION_TIMEOUT_MS)
                    else:
                        await loc.type(text, timeout=_ACTION_TIMEOUT_MS)

                except Exception as e:
                    return ToolResult(ok=False, data=None, error=_fmt_action_error("Type", e, selector_in))

                state.active_session = session_name
                return ToolResult(ok=True, data={"selector": selector_in, "typed_chars": len(text)}, error=None)

        except RuntimeError as e:
            return ToolResult(ok=False, data=None, error=str(e))
        except Exception as e:
            return ToolResult(ok=False, data=None, error=f"browser.type failed: {e}")


class BrowserScreenshotTool(Tool):
    name = "browser.screenshot"
    category = "browser"
    description = "Take a screenshot of the current page."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Optional output path (defaults to temp file)."},
            "session": {"type": "string", "description": "Optional session name. Default is current active session."},
        },
        "required": [],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            lane = _ACTION_BROWSER_LANE
            state = _state_for_lane(lane)
            session_name = _get_session_name(args, lane=lane)
            out_path = _resolve_screenshot_path((args.get("path") or "").strip() or None)
            sess, page = await _ensure_session_page(session_name, lane=lane)

            async with sess.lock:
                reh_err = await _rehydrate_if_needed(sess, page)
                if reh_err:
                    return ToolResult(ok=False, data=None, error=reh_err)

                nav_err = _ensure_navigated(page)
                if nav_err:
                    return ToolResult(ok=False, data=None, error=nav_err)

                try:
                    await page.screenshot(path=out_path, full_page=True)
                except Exception as e:
                    return ToolResult(ok=False, data=None, error=_fmt_action_error("Screenshot", e))

                try:
                    title = await page.title()
                except Exception:
                    title = ""

                state.active_session = session_name
                return ToolResult(ok=True, data={"path": out_path, "url": page.url, "title": title}, error=None)

        except RuntimeError as e:
            return ToolResult(ok=False, data=None, error=str(e))
        except Exception as e:
            return ToolResult(ok=False, data=None, error=f"browser.screenshot failed: {e}")


class BrowserExtractTool(Tool):
    name = "browser.extract"
    category = "browser"
    description = "Extract strings from page elements (CSS selector)."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector for elements to extract."},
            "attribute": {"type": "string", "description": "Optional attribute. If omitted, returns textContent."},
            "session": {"type": "string", "description": "Optional session name. Default is current active session."},
        },
        "required": ["selector"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            selector = (args.get("selector") or "").strip()
            if not selector:
                return ToolResult(ok=False, data=None, error="Missing required param: selector")

            attribute = (args.get("attribute") or "").strip() or None
            lane = _ACTION_BROWSER_LANE
            state = _state_for_lane(lane)
            session_name = _get_session_name(args, lane=lane)
            sess, page = await _ensure_session_page(session_name, lane=lane)

            async with sess.lock:
                reh_err = await _rehydrate_if_needed(sess, page)
                if reh_err:
                    return ToolResult(ok=False, data=None, error=reh_err)

                nav_err = _ensure_navigated(page)
                if nav_err:
                    return ToolResult(ok=False, data=None, error=nav_err)

                try:
                    loc = page.locator(selector)
                    count = await loc.count()
                    n = min(count, _EXTRACT_MAX_ITEMS)
                except Exception as e:
                    return ToolResult(ok=False, data=None, error=_fmt_action_error("Extract", e, selector))

                items: list[str] = []
                try:
                    for i in range(n):
                        el = loc.nth(i)
                        if attribute:
                            val = await el.get_attribute(attribute)
                            if val is None:
                                continue
                            s = str(val).strip()
                        else:
                            val = await el.text_content()
                            if val is None:
                                continue
                            s = str(val).strip()
                        if s:
                            items.append(s)
                except Exception as e:
                    return ToolResult(ok=False, data=None, error=_fmt_action_error("Extract", e, selector))

                state.active_session = session_name
                return ToolResult(ok=True, data=items, error=None)

        except RuntimeError as e:
            return ToolResult(ok=False, data=None, error=str(e))
        except Exception as e:
            return ToolResult(ok=False, data=None, error=f"browser.extract failed: {e}")


class BrowserCloseTool(Tool):
    name = "browser.close"
    category = "browser"
    description = "Close the shared Chromium browser and cleanup the Playwright instance."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            # Also ensure we don't deadlock by acquiring session locks one-by-one.
            # Since we are tearing down, we try non-blocking lock acquisition with best-effort.
            # If a session is mid-flight, caller should retry close after that action finishes.
            for lane_name, state in list(_BROWSER_STATES.items()):
                for name, sess in list(state.sessions.items()):
                    if sess.lock.locked():
                        return ToolResult(
                            ok=False,
                            data=None,
                            error=(
                                f"browser.close: lane {lane_name!r} session {name!r} is busy "
                                "(in-flight operation). Retry after it completes."
                            ),
                        )
            await shutdown_browser()
            return ToolResult(ok=True, data={"closed": True}, error=None)
        except Exception as e:
            return ToolResult(ok=False, data=None, error=f"browser.close failed: {e}")


# Export for registries that auto-discover tools in a module
TOOLS: list[Tool] = [
    BrowserOpenTool(),
    BrowserClickTool(),
    BrowserTypeTool(),
    BrowserScreenshotTool(),
    BrowserExtractTool(),
    BrowserCloseTool(),
]
