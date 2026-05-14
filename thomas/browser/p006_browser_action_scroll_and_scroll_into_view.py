"""P006 - Browser actions: scroll and scroll-into-view.

This module implements two small but surprisingly finicky browser actions:

- Scroll the page viewport by a pixel delta.
- Scroll a specific element into view.

Design goals (important for Thomas):
- **No hard dependency** on a specific browser backend at import-time.
- Compatible with both sync and async Playwright-style APIs (best-effort).
- Deterministic, machine-readable errors.

Public API:
- ViewportScrollRequest / ViewportScrollResult
- ScrollIntoViewRequest / ScrollIntoViewResult
- perform_viewport_scroll(page, request)
- perform_scroll_into_view(page, request)
- ACTION_HANDLERS: mapping of action-name -> handler callable
- as_json_schema(): minimal schema for automation
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

# ---------------------------------------------------------------------------
# Deterministic errors
# ---------------------------------------------------------------------------


class BrowserActionError(RuntimeError):
    """Deterministic browser action error.

    The goal is for callers (CLI, automation, tools) to be able to branch on
    `code` without parsing human-readable strings.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})
        self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


# ---------------------------------------------------------------------------
# Input / output contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ViewportScrollRequest:
    """Request to scroll the viewport by a delta."""

    delta_x: int = 0
    delta_y: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ViewportScrollRequest:
        if not isinstance(data, Mapping):
            raise BrowserActionError(
                "INVALID_INPUT",
                "scroll input must be an object",
                details={"received_type": type(data).__name__},
            )

        dx = data.get("delta_x", data.get("x", 0))
        dy = data.get("delta_y", data.get("y", 0))

        if not isinstance(dx, int) or not isinstance(dy, int):
            raise BrowserActionError(
                "INVALID_INPUT",
                "scroll deltas must be integers",
                details={"delta_x_type": type(dx).__name__, "delta_y_type": type(dy).__name__},
            )

        if dx == 0 and dy == 0:
            raise BrowserActionError(
                "INVALID_INPUT",
                "scroll requires a non-zero delta_x or delta_y",
            )

        return cls(delta_x=dx, delta_y=dy)


@dataclass(frozen=True)
class ViewportScrollResult:
    delta_x: int
    delta_y: int

    def to_dict(self) -> dict[str, Any]:
        return {"delta_x": self.delta_x, "delta_y": self.delta_y}


@dataclass(frozen=True)
class ScrollIntoViewRequest:
    """Request to scroll an element matching `selector` into view."""

    selector: str
    timeout_ms: int | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScrollIntoViewRequest:
        if not isinstance(data, Mapping):
            raise BrowserActionError(
                "INVALID_INPUT",
                "scroll-into-view input must be an object",
                details={"received_type": type(data).__name__},
            )

        selector = data.get("selector") or data.get("css") or data.get("query")
        if not isinstance(selector, str) or not selector.strip():
            raise BrowserActionError(
                "INVALID_INPUT",
                "scroll-into-view requires a non-empty 'selector' string",
            )

        timeout_ms = data.get("timeout_ms", data.get("timeout"))
        if timeout_ms is not None and not isinstance(timeout_ms, int):
            raise BrowserActionError(
                "INVALID_INPUT",
                "timeout_ms must be an integer (milliseconds)",
                details={"timeout_ms_type": type(timeout_ms).__name__},
            )
        if isinstance(timeout_ms, int) and timeout_ms <= 0:
            raise BrowserActionError(
                "INVALID_INPUT",
                "timeout_ms must be positive",
                details={"timeout_ms": timeout_ms},
            )

        return cls(selector=selector.strip(), timeout_ms=timeout_ms)


@dataclass(frozen=True)
class ScrollIntoViewResult:
    selector: str
    found: bool
    method: str  # "locator" | "js"

    def to_dict(self) -> dict[str, Any]:
        return {"selector": self.selector, "found": self.found, "method": self.method}


# ---------------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------------


async def _maybe_await(value: Any) -> Any:
    """Await value if it's awaitable; otherwise return it."""

    if inspect.isawaitable(value):
        return await value
    return value


def _looks_like_timeout(exc: BaseException) -> bool:
    name = exc.__class__.__name__.lower()
    mod = (exc.__class__.__module__ or "").lower()
    msg = str(exc).lower()

    # Prefer strong signals.
    if "timeout" in name:
        return True
    if "playwright" in mod and "timeout" in msg:
        return True
    return False


def _normalize_for_queryselector(selector: str) -> str | None:
    """Return a CSS selector usable by document.querySelector, or None.

    Playwright-style selectors like `text=...` are *not* CSS selectors.
    """

    s = selector.strip()
    if not s:
        return None

    # Allow explicit css= prefix (common in some automation stacks).
    if s.startswith("css="):
        s = s[len("css=") :].strip()

    # Playwright and similar selector engines:
    non_css_prefixes = (
        "text=",
        "xpath=",
        "id=",
        "role=",
        "label=",
        "placeholder=",
        "alt=",
        "title=",
    )
    if any(s.startswith(p) for p in non_css_prefixes):
        return None

    # Playwright's selector chaining uses `>>`.
    if " >> " in s or s.startswith("//") or s.startswith("..//"):
        return None

    return s


def _get_callable(obj: Any, *names: str) -> Callable[..., Any] | None:
    for name in names:
        fn = getattr(obj, name, None)
        if callable(fn):
            return fn
    return None


# ---------------------------------------------------------------------------
# Core implementations
# ---------------------------------------------------------------------------


async def perform_viewport_scroll(page: Any, request: ViewportScrollRequest) -> ViewportScrollResult:
    """Scroll the viewport on the given page."""

    if page is None:
        raise BrowserActionError("MISSING_CONTEXT", "scroll requires a page")

    try:
        mouse = getattr(page, "mouse", None)
        wheel = getattr(mouse, "wheel", None) if mouse is not None else None
        if callable(wheel):
            await _maybe_await(wheel(request.delta_x, request.delta_y))
            return ViewportScrollResult(delta_x=request.delta_x, delta_y=request.delta_y)

        evaluate = _get_callable(page, "evaluate", "eval")
        if evaluate is not None:
            js = "([dx, dy]) => { window.scrollBy(dx, dy); return {dx, dy}; }"
            await _maybe_await(evaluate(js, [request.delta_x, request.delta_y]))
            return ViewportScrollResult(delta_x=request.delta_x, delta_y=request.delta_y)

        raise BrowserActionError(
            "UNSUPPORTED_BACKEND",
            "page does not support scrolling (missing mouse.wheel and evaluate)",
            details={"page_type": type(page).__name__},
        )
    except BrowserActionError:
        raise
    except Exception as exc:  # pragma: no cover
        raise BrowserActionError(
            "EXTERNAL_FAILURE",
            "browser backend failed during scroll",
            details={"delta_x": request.delta_x, "delta_y": request.delta_y},
            cause=exc,
        )


async def perform_scroll_into_view(page: Any, request: ScrollIntoViewRequest) -> ScrollIntoViewResult:
    """Scroll an element into view.

    Behavior:
    - Prefer a Playwright-style locator path when available.
    - Fall back to JavaScript `document.querySelector(...).scrollIntoView(...)` for CSS selectors.
    - If the element cannot be found, raise a deterministic `ELEMENT_NOT_FOUND` error.
    """

    if page is None:
        raise BrowserActionError("MISSING_CONTEXT", "scroll-into-view requires a page")

    # 1) Locator-based path (supports non-CSS selectors in Playwright).
    locator_factory = getattr(page, "locator", None)
    if callable(locator_factory):
        try:
            locator = locator_factory(request.selector)
            scroll_fn = getattr(locator, "scroll_into_view_if_needed", None)
            if callable(scroll_fn):
                kwargs: dict[str, Any] = {}
                if request.timeout_ms is not None:
                    # Playwright uses `timeout` kw.
                    kwargs["timeout"] = request.timeout_ms
                await _maybe_await(scroll_fn(**kwargs))
                return ScrollIntoViewResult(selector=request.selector, found=True, method="locator")
        except Exception as exc:
            if _looks_like_timeout(exc):
                raise BrowserActionError(
                    "ELEMENT_NOT_FOUND",
                    "element was not found or could not be scrolled into view before timeout",
                    details={"selector": request.selector, "timeout_ms": request.timeout_ms},
                    cause=exc,
                )
            # Otherwise, try JS fallback below.

    # 2) JS fallback (CSS selectors only).
    css_selector = _normalize_for_queryselector(request.selector)
    if css_selector is None:
        raise BrowserActionError(
            "UNSUPPORTED_SELECTOR",
            "selector is not a CSS selector and the browser backend does not expose a locator API",
            details={"selector": request.selector},
        )

    evaluate = _get_callable(page, "evaluate", "eval")
    if evaluate is None:
        raise BrowserActionError(
            "UNSUPPORTED_BACKEND",
            "page does not support scroll-into-view (missing locator and evaluate)",
            details={"page_type": type(page).__name__},
        )

    try:
        js = (
            "(selector) => {\n"
            "  try {\n"
            "    const el = document.querySelector(selector);\n"
            "    if (!el) return { ok: false, found: false };\n"
            "    el.scrollIntoView({ block: 'center', inline: 'center' });\n"
            "    return { ok: true, found: true };\n"
            "  } catch (e) {\n"
            "    return { ok: false, found: false, error: String(e) };\n"
            "  }\n"
            "}"
        )
        res = await _maybe_await(evaluate(js, css_selector))
    except Exception as exc:  # pragma: no cover
        raise BrowserActionError(
            "EXTERNAL_FAILURE",
            "browser backend failed during scroll-into-view",
            details={"selector": request.selector},
            cause=exc,
        )

    if isinstance(res, Mapping):
        ok = bool(res.get("ok"))
        found = bool(res.get("found"))
        if ok and found:
            return ScrollIntoViewResult(selector=request.selector, found=True, method="js")
        if not found:
            # If error exists, treat invalid selector as INVALID_INPUT.
            if res.get("error"):
                raise BrowserActionError(
                    "INVALID_INPUT",
                    "invalid CSS selector for scroll-into-view",
                    details={"selector": request.selector, "error": str(res.get("error"))},
                )
            raise BrowserActionError(
                "ELEMENT_NOT_FOUND",
                "element was not found for scroll-into-view",
                details={"selector": request.selector},
            )

    # Unexpected return type from backend.
    raise BrowserActionError(
        "EXTERNAL_FAILURE",
        "unexpected result from browser backend during scroll-into-view",
        details={"selector": request.selector, "result_type": type(res).__name__},
    )


# ---------------------------------------------------------------------------
# Dispatcher compatibility layer
# ---------------------------------------------------------------------------


def _extract_page_and_payload(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, Mapping[str, Any]]:
    """Best-effort extraction of (page, payload) from common dispatcher call styles."""

    # Explicit kwargs.
    if "page" in kwargs:
        payload = kwargs.get("payload") or kwargs.get("params") or kwargs.get("input") or {}
        if isinstance(payload, Mapping):
            return kwargs["page"], payload

    # Common positional: (page, payload)
    if len(args) >= 2 and isinstance(args[1], Mapping):
        return args[0], args[1]

    # Context mapping: {page, payload/params/input}
    if len(args) == 1 and isinstance(args[0], Mapping):
        ctx = args[0]
        page = ctx.get("page") or ctx.get("current_page")
        payload = ctx.get("payload") or ctx.get("params") or ctx.get("input") or {}
        if isinstance(payload, Mapping):
            return page, payload

    # Context object: ctx.page, ctx.payload/ctx.params/ctx.input
    if len(args) == 1:
        ctx_obj = args[0]
        page = getattr(ctx_obj, "page", None) or getattr(ctx_obj, "current_page", None)
        payload = (
            getattr(ctx_obj, "payload", None)
            or getattr(ctx_obj, "params", None)
            or getattr(ctx_obj, "input", None)
            or {}
        )
        if isinstance(payload, Mapping):
            return page, payload

    raise BrowserActionError(
        "MISSING_CONTEXT",
        "unable to determine page and payload for browser action",
        details={"args_len": len(args), "kwargs_keys": sorted(kwargs.keys())},
    )


async def handle_scroll(*args: Any, **kwargs: Any) -> dict[str, Any]:
    page, payload = _extract_page_and_payload(args, kwargs)
    req = ViewportScrollRequest.from_dict(payload)
    res = await perform_viewport_scroll(page, req)
    return {"action": "scroll", **res.to_dict()}


async def handle_scroll_into_view(*args: Any, **kwargs: Any) -> dict[str, Any]:
    page, payload = _extract_page_and_payload(args, kwargs)
    req = ScrollIntoViewRequest.from_dict(payload)
    res = await perform_scroll_into_view(page, req)
    return {"action": "scroll_into_view", **res.to_dict()}


ACTION_HANDLERS: dict[str, Callable[..., Any]] = {
    "scroll": handle_scroll,
    "scroll_into_view": handle_scroll_into_view,
    # Friendly aliases (input side only).
    "scroll-into-view": handle_scroll_into_view,
}


def as_json_schema() -> dict[str, Any]:
    """Minimal JSON-schema-like description for automation."""

    return {
        "scroll": {
            "type": "object",
            "required": ["delta_y"],
            "properties": {
                "delta_x": {"type": "integer"},
                "delta_y": {"type": "integer"},
            },
        },
        "scroll_into_view": {
            "type": "object",
            "required": ["selector"],
            "properties": {
                "selector": {"type": "string"},
                "timeout_ms": {"type": "integer", "minimum": 1},
            },
        },
    }
