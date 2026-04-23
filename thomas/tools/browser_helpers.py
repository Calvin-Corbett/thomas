from __future__ import annotations

import re
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover
    PlaywrightError = Exception  # type: ignore[assignment]
    PlaywrightTimeoutError = TimeoutError  # type: ignore[assignment]


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise ValueError("Missing required param: url")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        u = "https://" + u
    return u


def _looks_like_css_or_xpath(selector: str) -> bool:
    s = (selector or "").strip()
    if not s:
        return False
    if s.startswith(("/", "xpath=", "css=", "text=", "role=", "id=", "data-testid=")):
        return True
    return bool(re.search(r"[#.\[\]>/~:+*]|^[a-zA-Z][\w-]*(\s|$)", s))


def _normalize_selector(selector: str) -> str:
    s = (selector or "").strip()
    if not s:
        raise ValueError("Missing required param: selector")
    return s


def _temp_screenshot_name() -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"{int(time.time() * 1000) % 1_000_000:06d}"
    return f"thomas_browser_{ts}_{suffix}.png"


def _resolve_screenshot_path(raw_path: str | None) -> str:
    if raw_path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
    else:
        path = Path(tempfile.gettempdir()) / _temp_screenshot_name()
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _fmt_action_error(action: str, err: Exception, detail: str = "") -> str:
    base = f"{action} failed"
    if detail:
        base += f" ({detail})"
    if isinstance(err, PlaywrightTimeoutError):
        return f"{base}: timed out"
    if isinstance(err, PlaywrightError):
        return f"{base}: {err}"
    return f"{base}: {type(err).__name__}: {err}"


def _fmt_nav_error(url: str, err: Exception, timeout_ms: int) -> str:
    if isinstance(err, PlaywrightTimeoutError):
        return f"Navigation to {url} timed out after {timeout_ms}ms"
    if isinstance(err, PlaywrightError):
        return f"Navigation to {url} failed: {err}"
    return f"Navigation to {url} failed: {type(err).__name__}: {err}"


async def _best_effort_stabilize(page: Any, *, max_ms: int = 3000) -> None:
    with suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=max_ms)


async def _best_effort_read_stabilize(page: Any, *, settle_ms: int = 200) -> None:
    with suppress(Exception):
        await page.wait_for_timeout(settle_ms)


def _ensure_navigated(page: Any) -> str | None:
    with suppress(Exception):
        if not page.url or page.url == "about:blank":
            return "No page is currently open. Use browser.open first."
        return None
    return "No page is currently open. Use browser.open first."


async def _resolve_locator_for_click(page: Any, selector: str) -> Any:
    s = _normalize_selector(selector)
    if s.startswith("role="):
        return page.locator(s).first
    if _looks_like_css_or_xpath(s):
        return page.locator(s).first
    return page.get_by_role("button", name=re.compile(re.escape(s), re.I)).or_(
        page.get_by_role("link", name=re.compile(re.escape(s), re.I))
    ).or_(page.get_by_text(s, exact=False)).first


def _direct_link_navigation_target(base_url: str, href: str) -> str | None:
    href_text = str(href or "").strip()
    if not href_text:
        return None
    lowered = href_text.lower()
    if lowered.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    target = urljoin(base_url or "", href_text)
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"}:
        return None
    return target


async def _navigate_via_locator_href(page: Any, locator: Any, *, timeout_ms: int) -> bool:
    base_url = ""
    with suppress(Exception):
        base_url = page.url or ""

    href = None
    with suppress(Exception):
        href = await locator.get_attribute("href")
    if href is None:
        return False

    target = _direct_link_navigation_target(base_url, str(href or ""))
    if not target or target.rstrip("/").lower() == str(base_url or "").rstrip("/").lower():
        return False
    with suppress(Exception):
        resp = await page.goto(target, wait_until="commit", timeout=timeout_ms)
        return resp is None or getattr(resp, "status", 0) < 400
    return False


async def _resolve_locator_for_type(page: Any, selector: str) -> Any:
    s = _normalize_selector(selector)
    if _looks_like_css_or_xpath(s):
        return page.locator(s).first
    return page.get_by_label(s, exact=False).or_(page.get_by_placeholder(s, exact=False)).or_(
        page.get_by_text(s, exact=False)
    ).first
