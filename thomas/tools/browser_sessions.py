from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PLAYWRIGHT_AVAILABLE = True
_PLAYWRIGHT_IMPORT_ERROR: str | None = None
try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright
except ImportError as exc:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False
    _PLAYWRIGHT_IMPORT_ERROR = str(exc)
    PlaywrightError = RuntimeError  # type: ignore[assignment]

_PREFERRED_BROWSER_EXECUTABLES = (
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
)
_ACTION_BROWSER_LANE = "action"
_READ_BROWSER_LANE = "read"
_NAV_TIMEOUT_MS = 30_000
_ACTION_TIMEOUT_MS = 5_000


@dataclass
class _SessionState:
    context: Any = None
    page: Any = None
    last_url: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class _BrowserState:
    pw: Any = None
    browser: Any = None
    headless: bool | None = None
    sessions: dict[str, _SessionState] = field(default_factory=dict)
    active_session: str = "default"


_BROWSER_STATES: dict[str, _BrowserState] = {}
_INIT_LOCKS: dict[str, asyncio.Lock] = {}


def _require_playwright() -> None:
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(f"Playwright is not installed/available: {_PLAYWRIGHT_IMPORT_ERROR}")


def _normalize_lane(lane: str | None) -> str:
    value = str(lane or "").strip().lower()
    if value == _READ_BROWSER_LANE:
        return _READ_BROWSER_LANE
    return _ACTION_BROWSER_LANE


def _state_for_lane(lane: str | None) -> _BrowserState:
    normalized = _normalize_lane(lane)
    state = _BROWSER_STATES.get(normalized)
    if state is None:
        state = _BrowserState()
        _BROWSER_STATES[normalized] = state
    return state


def _lock_for_lane(lane: str | None) -> asyncio.Lock:
    normalized = _normalize_lane(lane)
    lock = _INIT_LOCKS.get(normalized)
    if lock is None:
        lock = asyncio.Lock()
        _INIT_LOCKS[normalized] = lock
    return lock


def _browser_launch_kwargs(headless: bool) -> dict[str, Any]:
    override = os.environ.get("THOMAS_BROWSER_EXECUTABLE", "").strip()
    candidates = ([override] if override else []) + list(_PREFERRED_BROWSER_EXECUTABLES)
    for raw in candidates:
        candidate = Path(str(raw or "").strip())
        if str(candidate) and candidate.exists():
            return {"headless": headless, "executable_path": str(candidate)}
    return {"headless": headless}


def _browser_context_kwargs() -> dict[str, Any]:
    return {"ignore_https_errors": True}


async def _cleanup_locked(*, lane: str) -> None:
    state = _state_for_lane(lane)
    for sess in list(state.sessions.values()):
        if sess.page is not None:
            with suppress(Exception):
                await sess.page.close()
            sess.page = None
        if sess.context is not None:
            with suppress(Exception):
                await sess.context.close()
            sess.context = None
        sess.last_url = None
    state.sessions.clear()
    state.active_session = "default"
    if state.browser is not None:
        with suppress(Exception):
            await state.browser.close()
        state.browser = None
    if state.pw is not None:
        with suppress(Exception):
            await state.pw.stop()
        state.pw = None
    state.headless = None


async def get_browser(*, headless: bool = True, lane: str = _ACTION_BROWSER_LANE) -> Any:
    _require_playwright()
    normalized_lane = _normalize_lane(lane)
    state = _state_for_lane(normalized_lane)
    async with _lock_for_lane(normalized_lane):
        relaunch = state.browser is None
        if state.browser is not None:
            with suppress(Exception):
                relaunch = bool(hasattr(state.browser, "is_connected") and not state.browser.is_connected())
        if state.headless is not None and state.headless != headless:
            relaunch = True
        if relaunch:
            await _cleanup_locked(lane=normalized_lane)
            state.pw = await async_playwright().start()
            state.browser = await state.pw.chromium.launch(**_browser_launch_kwargs(headless))
            state.headless = headless
        return state.browser


def _get_session_name(args: dict[str, Any], *, lane: str = _ACTION_BROWSER_LANE) -> str:
    value = str(args.get("session") or "").strip()
    if value:
        return value
    return _state_for_lane(lane).active_session or "default"


async def _ensure_session_page(
    session_name: str,
    *,
    headless: bool | None = None,
    lane: str = _ACTION_BROWSER_LANE,
) -> tuple[_SessionState, Any]:
    normalized_lane = _normalize_lane(lane)
    state = _state_for_lane(normalized_lane)
    desired_headless = bool(headless) if headless is not None else (state.headless if state.headless is not None else True)
    browser = await get_browser(headless=desired_headless, lane=normalized_lane)
    async with _lock_for_lane(normalized_lane):
        sess = state.sessions.get(session_name)
        if sess is None:
            sess = _SessionState()
            state.sessions[session_name] = sess
        if sess.page is not None:
            page_closed = True
            with suppress(Exception):
                if sess.page.is_closed():
                    page_closed = True
                else:
                    page_closed = False
            if page_closed:
                sess.page = None
        if sess.context is None:
            sess.context = await browser.new_context(**_browser_context_kwargs())
        if sess.page is None:
            sess.page = await sess.context.new_page()
            with suppress(Exception):
                sess.page.set_default_navigation_timeout(_NAV_TIMEOUT_MS)
            with suppress(Exception):
                sess.page.set_default_timeout(_ACTION_TIMEOUT_MS)
        return sess, sess.page


async def warm_browser_session(
    session_name: str = "default",
    *,
    headless: bool = True,
    lane: str = _ACTION_BROWSER_LANE,
) -> None:
    with suppress(Exception):
        normalized_lane = _normalize_lane(lane)
        await _ensure_session_page(session_name, headless=headless, lane=normalized_lane)
        _state_for_lane(normalized_lane).active_session = session_name


async def shutdown_browser(*, lane: str | None = None) -> None:
    if lane is None:
        for normalized_lane in list(_BROWSER_STATES.keys()):
            async with _lock_for_lane(normalized_lane):
                await _cleanup_locked(lane=normalized_lane)
        return
    normalized_lane = _normalize_lane(lane)
    async with _lock_for_lane(normalized_lane):
        await _cleanup_locked(lane=normalized_lane)


async def _rehydrate_if_needed(sess: _SessionState, page: Any) -> str | None:
    if not sess.last_url:
        return None
    try:
        if page.url and page.url != "about:blank":
            return None
        await page.goto(sess.last_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        return None
    except (RuntimeError, OSError, ValueError, AttributeError, PlaywrightError) as exc:
        return f"Could not re-open previous page {sess.last_url}: {exc}"
