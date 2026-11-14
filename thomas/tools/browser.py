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

import asyncio
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- Thomas types ---
try:
    from thomas.tools.base import Tool, ToolResult  # type: ignore
except Exception:  # pragma: no cover
    try:
        from thomas.tools.tool import Tool, ToolResult  # type: ignore
    except Exception as e:  # pragma: no cover
        raise ImportError("Could not import Tool/ToolResult. Expected thomas.tools.base or thomas.tools.tool.") from e

from thomas.tools.browser_page import (
    _clean_text,
    _fmt_action_error,
    _fmt_nav_error,
    _looks_like_css_or_xpath,
    _normalize_selector,
    _normalize_url,
    _resolve_screenshot_path,
    _temp_screenshot_name,
    workspace_file_url,
)
from thomas.tools.browser_reading import (
    _extract_best_text,
    _resolve_locator_for_click,
    _resolve_locator_for_type,
)

# --- Playwright ---
_PLAYWRIGHT_AVAILABLE = True
_PLAYWRIGHT_IMPORT_ERROR: str | None = None
try:
    from playwright.async_api import (  # type: ignore
        Browser,
        BrowserContext,
        Locator,
        Page,
        async_playwright,
    )
    from playwright.async_api import (
        Error as PlaywrightError,
    )
    from playwright.async_api import (
        TimeoutError as PlaywrightTimeoutError,
    )
except Exception as e:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False
    _PLAYWRIGHT_IMPORT_ERROR = str(e)


# ----------------------------
# Constants
# ----------------------------

_NAV_TIMEOUT_MS = 30_000
_ACTION_TIMEOUT_MS = 5_000
_EXTRACT_MAX_ITEMS = 2000


# ----------------------------
# Shared singleton browser + session pages
# ----------------------------


@dataclass
class _SessionState:
    context: BrowserContext | None = None
    page: Page | None = None
    last_url: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class _BrowserState:
    pw: Any = None
    browser: Browser | None = None
    headless: bool | None = None
    sessions: dict[str, _SessionState] = field(default_factory=dict)
    active_session: str = "default"
    # True from stop_browser until start_browser: no call may launch Playwright again in between.
    stopped: bool = False


_STATE = _BrowserState()

# Init lock protects Playwright/browser lifecycle and session creation/teardown
_init_lock = asyncio.Lock()


# ----------------------------
# Helper utilities
# ----------------------------


def _require_playwright() -> None:
    if not _PLAYWRIGHT_AVAILABLE:
        msg = _PLAYWRIGHT_IMPORT_ERROR or "unknown import error"
        raise RuntimeError(
            "Playwright is not available. Install it and Chromium:\n"
            "  pip install playwright\n"
            "  playwright install chromium\n"
            f"Import error: {msg}"
        )


async def _best_effort_stabilize(page: Page, *, max_ms: int = 3000) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=max_ms)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=max_ms)
    except Exception:
        pass


# ----------------------------
# Lifecycle: singleton browser + session pages
# ----------------------------


async def _cleanup_locked() -> None:
    """Close all sessions and the browser+playwright. Caller must hold _init_lock."""
    # Close sessions first
    for sess in list(_STATE.sessions.values()):
        if sess.page is not None:
            try:
                await sess.page.close()
            except Exception:
                pass
            sess.page = None
        if sess.context is not None:
            try:
                await sess.context.close()
            except Exception:
                pass
            sess.context = None
        sess.last_url = None

    _STATE.sessions.clear()
    _STATE.active_session = "default"

    if _STATE.browser is not None:
        try:
            await _STATE.browser.close()
        except Exception:
            pass
        _STATE.browser = None

    if _STATE.pw is not None:
        try:
            await _STATE.pw.stop()
        except Exception:
            pass
        _STATE.pw = None

    _STATE.headless = None


async def get_browser(*, headless: bool = True) -> Browser:
    """Get or create the shared Chromium browser (singleton)."""
    _require_playwright()
    if _STATE.stopped:
        raise RuntimeError("The browser is turned off, so it cannot be opened.")

    async with _init_lock:
        if _STATE.stopped:  # a stop came while this call waited its turn
            raise RuntimeError("The browser is turned off, so it cannot be opened.")
        relaunch = False
        if _STATE.browser is None:
            relaunch = True
        else:
            try:
                if hasattr(_STATE.browser, "is_connected") and not _STATE.browser.is_connected():
                    relaunch = True
            except Exception:
                relaunch = True

        if _STATE.headless is not None and _STATE.headless != headless:
            relaunch = True

        if relaunch:
            await _cleanup_locked()
            _STATE.pw = await async_playwright().start()
            _STATE.browser = await _STATE.pw.chromium.launch(headless=headless)
            _STATE.headless = headless

        return _STATE.browser  # type: ignore[return-value]


async def stop_browser() -> None:
    """Close every session, the browser and Playwright, and refuse to launch another until ``start_browser``.

    Unlike ``browser.close`` this does not wait for a session that is partway through a call: that call fails, because
    its page is gone, and a call that begins later is refused.
    """
    _STATE.stopped = True
    async with _init_lock:
        await _cleanup_locked()


def start_browser() -> None:
    """Let calls launch the browser again after ``stop_browser``. Nothing is launched until one is made."""
    _STATE.stopped = False


def _get_session_name(args: dict[str, Any]) -> str:
    s = (args.get("session") or "").strip()
    if s:
        return s
    return _STATE.active_session or "default"


async def _ensure_session_page(session_name: str, *, headless: bool | None = None) -> tuple[_SessionState, Page]:
    """Ensure session exists with an alive context+page."""
    desired_headless = (
        bool(headless) if headless is not None else (_STATE.headless if _STATE.headless is not None else True)
    )
    browser = await get_browser(headless=desired_headless)

    async with _init_lock:
        sess = _STATE.sessions.get(session_name)
        if sess is None:
            sess = _SessionState()
            _STATE.sessions[session_name] = sess

        # Heal closed page
        if sess.page is not None:
            try:
                if sess.page.is_closed():
                    sess.page = None
            except Exception:
                sess.page = None

        if sess.context is None:
            sess.context = await browser.new_context()

        if sess.page is None:
            sess.page = await sess.context.new_page()
            try:
                sess.page.set_default_navigation_timeout(_NAV_TIMEOUT_MS)
            except Exception:
                pass
            try:
                sess.page.set_default_timeout(_ACTION_TIMEOUT_MS)
            except Exception:
                pass

        return sess, sess.page


async def _rehydrate_if_needed(sess: _SessionState, page: Page) -> str | None:
    """If page is blank and we have a last_url, navigate back so actions can continue."""
    try:
        cur = page.url or ""
    except Exception:
        cur = ""
    if cur and cur != "about:blank":
        return None
    if not sess.last_url:
        return None

    try:
        resp = await page.goto(sess.last_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        if resp is not None:
            try:
                if resp.status >= 400:
                    return f"HTTP {resp.status} while rehydrating last page: {sess.last_url}"
            except Exception:
                pass
        await _best_effort_stabilize(page, max_ms=2500)
        return None
    except Exception as e:
        return _fmt_nav_error(sess.last_url, e, _NAV_TIMEOUT_MS)


def _ensure_navigated(page: Page) -> str | None:
    try:
        u = page.url or ""
    except Exception:
        return "Unable to read current page URL."
    if not u or u == "about:blank":
        return "No active navigated page. Use browser.open first."
    return None


# ----------------------------
# "Consumer-friendly" locator resolution
# ----------------------------


class BrowserOpenTool(Tool):
    name = "browser.open"
    category = "browser"
    description = (
        "Navigate to a URL and return page title + cleaned text (max 8000 chars). "
        "A file:// path inside your own workspace is allowed, so you can open a page "
        "you just wrote without serving it yourself."
    )

    def __init__(self, workspace: str | Path | None = None) -> None:
        # Where this run's own output lives. None means no file:// access at
        # all -- the allowance is opt-in per run, never the default.
        self._workspace = workspace

    def for_workspace(self, workspace: str | Path | None) -> BrowserOpenTool:
        """The same tool for another run's folder, which is the only place ``file://`` is allowed."""
        return BrowserOpenTool(workspace)

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to navigate to."},
            "wait_for": {"type": "string", "description": "Optional CSS selector to wait for."},
            "headless": {"type": "boolean", "description": "Run headless (default true).", "default": True},
            "session": {
                "type": "string",
                "description": "Optional session name (isolated cookies). Default 'default'.",
            },
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
            # An agent looking at what it just wrote. Confined to this run's own
            # workspace and resolved through symlinks (browser_page), so it is a
            # separate narrow allowance rather than a hole in the guard below.
            own_output = workspace_file_url(raw_url, self._workspace)
            if own_output is not None:
                url = own_output.as_uri()
            # SSRF guard before opening a browser session or navigating. Blocks
            # cloud-metadata/link-local always and honors the operator host
            # policy, matching web.fetch / eng.web_extract.
            from thomas.tools.web_search_providers import check_outbound_url

            policy_err = None if own_output is not None else check_outbound_url(url)
            if policy_err:
                return ToolResult(ok=False, data=None, error=policy_err)
            wait_for = (args.get("wait_for") or "").strip() or None
            headless = bool(args.get("headless", True))
            session_name = _get_session_name(args)

            sess, page = await _ensure_session_page(session_name, headless=headless)

            async with sess.lock:
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
                except Exception as e:
                    return ToolResult(ok=False, data=None, error=_fmt_nav_error(url, e, _NAV_TIMEOUT_MS))

                if resp is not None:
                    # Re-validate the final URL in case a redirect landed on a
                    # blocked host (e.g. a 302 to the cloud metadata endpoint).
                    # check_outbound_url never raises; if resp.url itself is
                    # unreadable the outer handler fails the call closed rather
                    # than returning unvalidated content.
                    final_err = check_outbound_url(str(resp.url))
                    if final_err:
                        return ToolResult(ok=False, data=None, error=final_err)
                    try:
                        status = resp.status
                        if status >= 400:
                            return ToolResult(ok=False, data=None, error=f"HTTP {status} while navigating to {url}")
                    except Exception:
                        pass

                if wait_for:
                    try:
                        await page.wait_for_selector(
                            _normalize_selector(wait_for), timeout=_NAV_TIMEOUT_MS, state="attached"
                        )
                    except Exception as e:
                        return ToolResult(
                            ok=False, data=None, error=_fmt_action_error("Wait for selector", e, wait_for)
                        )

                await _best_effort_stabilize(page, max_ms=5000)

                try:
                    title = await page.title()
                except Exception:
                    title = ""

                text = _clean_text(await _extract_best_text(page))

                # Remember last good URL for rehydration
                try:
                    sess.last_url = page.url
                except Exception:
                    sess.last_url = url

                _STATE.active_session = session_name

                return ToolResult(ok=True, data={"url": page.url, "title": title, "text": text}, error=None)

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

            session_name = _get_session_name(args)
            sess, page = await _ensure_session_page(session_name)

            async with sess.lock:
                reh_err = await _rehydrate_if_needed(sess, page)
                if reh_err:
                    return ToolResult(ok=False, data=None, error=reh_err)

                nav_err = _ensure_navigated(page)
                if nav_err:
                    return ToolResult(ok=False, data=None, error=nav_err)

                before_url = ""
                try:
                    before_url = page.url or ""
                except Exception:
                    pass

                try:
                    loc = await _resolve_locator_for_click(page, selector_in)
                    await loc.wait_for(state="attached", timeout=timeout_ms)
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

                await _best_effort_stabilize(page, max_ms=3000)

                # Track URL changes
                try:
                    after_url = page.url or ""
                    if after_url and after_url != "about:blank":
                        sess.last_url = after_url
                except Exception:
                    pass

                _STATE.active_session = session_name

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
            session_name = _get_session_name(args)
            sess, page = await _ensure_session_page(session_name)

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

                _STATE.active_session = session_name
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
            session_name = _get_session_name(args)
            out_path = _resolve_screenshot_path((args.get("path") or "").strip() or None)
            sess, page = await _ensure_session_page(session_name)

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

                _STATE.active_session = session_name
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
            session_name = _get_session_name(args)
            sess, page = await _ensure_session_page(session_name)

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

                _STATE.active_session = session_name
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
            async with _init_lock:
                # Also ensure we don't deadlock by acquiring session locks one-by-one.
                # Since we are tearing down, we try non-blocking lock acquisition with best-effort.
                # If a session is mid-flight, caller should retry close after that action finishes.
                for name, sess in list(_STATE.sessions.items()):
                    if sess.lock.locked():
                        return ToolResult(
                            ok=False,
                            data=None,
                            error=f"browser.close: session {name!r} is busy (in-flight operation). Retry after it completes.",
                        )
                await _cleanup_locked()
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


def register_browser_tools(registry: Any, workspace: str | Path | None = None) -> int:
    """Register the Playwright browser tools into a ToolRegistry.

    Gated on Playwright being importable: if the ``playwright`` package is not
    installed the tools would only fail at call time with a RuntimeError, so we
    skip registration entirely and return 0 rather than advertising tools that
    cannot run. Returns the number of tools registered.

    ``workspace`` is this run's own output directory. Passing it lets
    ``browser.open`` read a ``file://`` path inside it and nothing else; leaving
    it out means no file access, which is what every caller that does not know
    its workspace should do.
    """
    import importlib.util

    if importlib.util.find_spec("playwright") is None:
        return 0
    count = 0
    for tool in TOOLS:
        # The open tool is rebuilt per registration so one process serving
        # several runs never shares one run's workspace with another.
        registry.register(BrowserOpenTool(workspace) if isinstance(tool, BrowserOpenTool) else tool)
        count += 1
    return count
