"""Prompt P002 - Browser navigate/open action.

This module provides Thomas-native behavior for two essential browser operations:

* **navigate**: move the current tab/page to a URL
* **open**: open a URL in a new tab/page

Design goals:
- Clear typed input/output contracts.
- Deterministic, machine-readable errors.
- Resilient adapter that can call a variety of likely browser-tool interfaces
  used across the Thomas codebase (and its underlying browser backends).
- JSON output that *never* crashes on non-serializable raw results.

Notes on async:
- A fully async entrypoint is provided (``async_p002_navigate_and_open``).
- The sync entrypoint (``run_p002_navigate_and_open``) is safe for CLI use.
  If called from inside an already-running event loop, it raises a deterministic
  error instead of deadlocking.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Optional
from urllib.parse import urlparse

NavigateOpenAction = Literal["navigate", "open"]


@dataclass(frozen=True, slots=True)
class NavigateAndOpenRequest:
    """Input contract for P002."""

    url: str
    action: NavigateOpenAction = "navigate"
    timeout_ms: Optional[int] = None
    profile: Optional[str] = None

    @staticmethod
    def from_mapping(data: Mapping[str, Any]) -> "NavigateAndOpenRequest":
        """Parse a request from a mapping.

        Supported aliases (to keep callers flexible):
        - action/mode/kind: "navigate" | "open"
        - open/new_tab/newTab: bool (true -> action="open")
        - timeout_ms/timeoutMs
        - browser_profile/browserProfile/profile
        """

        if not isinstance(data, Mapping):
            raise InvalidNavigateAndOpenInput(
                "Request must be a mapping.",
                details={"expected": "mapping"},
            )

        url = data.get("url")

        action = data.get("action") or data.get("mode") or data.get("kind")
        open_flag = data.get("open")
        new_tab = data.get("new_tab") if "new_tab" in data else data.get("newTab")

        if action is None:
            if open_flag is True or new_tab is True:
                action = "open"
            else:
                action = "navigate"

        timeout_ms = data.get("timeout_ms")
        if timeout_ms is None and "timeoutMs" in data:
            timeout_ms = data.get("timeoutMs")

        profile = data.get("profile")
        if profile is None and "browser_profile" in data:
            profile = data.get("browser_profile")
        if profile is None and "browserProfile" in data:
            profile = data.get("browserProfile")

        return NavigateAndOpenRequest(
            url=_coerce_url(url),
            action=_coerce_action(action),
            timeout_ms=_coerce_timeout_ms(timeout_ms),
            profile=_coerce_optional_str(profile, field_name="profile"),
        )


@dataclass(frozen=True, slots=True)
class NavigateAndOpenResult:
    """Output contract for P002."""

    ok: bool
    action: NavigateOpenAction
    url: str
    tab_id: Optional[str] = None
    raw: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "url": self.url,
            "tab_id": self.tab_id,
            "raw": _json_safe(self.raw),
        }


class NavigateAndOpenError(RuntimeError):
    """Base class for deterministic P002 failures."""

    code: str = "browser.navigate_open.error"

    def __init__(self, message: str, *, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": _json_safe(self.details)}


class InvalidNavigateAndOpenInput(NavigateAndOpenError):
    code = "browser.navigate_open.invalid_input"


class MissingBrowserConfiguration(NavigateAndOpenError):
    code = "browser.navigate_open.missing_config"


class BrowserOperationFailed(NavigateAndOpenError):
    code = "browser.navigate_open.external_failure"


class SyncCalledFromAsyncContext(NavigateAndOpenError):
    code = "browser.navigate_open.sync_called_from_async"


INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "url": {"type": "string", "description": "Absolute URL to open/navigate."},
        "action": {
            "type": "string",
            "enum": ["navigate", "open"],
            "description": "navigate current tab or open in new tab",
        },
        "timeout_ms": {
            "type": "integer",
            "minimum": 1,
            "description": "Optional timeout in milliseconds.",
        },
        "profile": {"type": "string", "description": "Optional browser profile."},
    },
    "required": ["url"],
}


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ok": {"type": "boolean"},
        "action": {"type": "string", "enum": ["navigate", "open"]},
        "url": {"type": "string"},
        "tab_id": {"type": ["string", "null"]},
        "raw": {},
    },
    "required": ["ok", "action", "url"],
}


def get_p002_schemas() -> dict[str, Any]:
    """Return machine-readable schema for automation."""

    return {"input": INPUT_SCHEMA, "output": OUTPUT_SCHEMA}


async def async_p002_navigate_and_open(
    request: NavigateAndOpenRequest,
    *,
    browser: Any | None = None,
) -> NavigateAndOpenResult:
    """Async entrypoint for P002."""

    _validate_url(request.url)

    if browser is None:
        browser = _resolve_browser_tool()

    raw = await _perform_async(browser, request)
    tab_id = _extract_tab_id(raw)
    return NavigateAndOpenResult(
        ok=True,
        action=request.action,
        url=request.url,
        tab_id=tab_id,
        raw=raw,
    )


def run_p002_navigate_and_open(
    request: NavigateAndOpenRequest,
    *,
    browser: Any | None = None,
) -> NavigateAndOpenResult:
    """Sync entrypoint for P002 (CLI-friendly).

    If called from inside a running event loop, raises a deterministic error.
    Use :func:`async_p002_navigate_and_open` from async contexts.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop -> safe to run.
        return asyncio.run(async_p002_navigate_and_open(request, browser=browser))

    raise SyncCalledFromAsyncContext(
        "run_p002_navigate_and_open cannot be called from an async context; use async_p002_navigate_and_open.",
        details={"action": request.action},
    )


def format_result_as_json(result: NavigateAndOpenResult) -> str:
    """Serialize a successful result to a JSON string."""

    return json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)


def format_error_as_json(err: NavigateAndOpenError) -> str:
    """Serialize an error result to a JSON string."""

    payload = {"ok": False, "error": err.to_dict()}
    return json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True)


def _coerce_action(value: Any) -> NavigateOpenAction:
    if not isinstance(value, str):
        raise InvalidNavigateAndOpenInput(
            "Field 'action' must be a string.",
            details={"field": "action"},
        )
    lowered = value.strip().lower()
    if lowered not in ("navigate", "open"):
        raise InvalidNavigateAndOpenInput(
            "Field 'action' must be 'navigate' or 'open'.",
            details={"field": "action", "value": value},
        )
    return lowered  # type: ignore[return-value]


def _coerce_timeout_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise InvalidNavigateAndOpenInput(
            "Field 'timeout_ms' must be an integer.",
            details={"field": "timeout_ms"},
        )
    if not isinstance(value, int):
        raise InvalidNavigateAndOpenInput(
            "Field 'timeout_ms' must be an integer.",
            details={"field": "timeout_ms"},
        )
    if value <= 0:
        raise InvalidNavigateAndOpenInput(
            "Field 'timeout_ms' must be > 0.",
            details={"field": "timeout_ms", "value": value},
        )
    return value


def _coerce_optional_str(value: Any, *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidNavigateAndOpenInput(
            f"Field '{field_name}' must be a string.",
            details={"field": field_name},
        )
    stripped = value.strip()
    return stripped or None


def _coerce_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidNavigateAndOpenInput(
            "Field 'url' must be a non-empty string.",
            details={"field": "url"},
        )
    return value.strip()


def _validate_url(url: str) -> None:
    if not isinstance(url, str) or not url.strip():
        raise InvalidNavigateAndOpenInput(
            "Field 'url' must be a non-empty string.",
            details={"field": "url"},
        )

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise InvalidNavigateAndOpenInput(
            "URL must be absolute and start with http:// or https://",
            details={"field": "url", "value": url},
        )
    if not parsed.netloc:
        raise InvalidNavigateAndOpenInput(
            "URL must include a host.",
            details={"field": "url", "value": url},
        )


def _resolve_browser_tool() -> Any:
    """Resolve the default browser tool/client.

    We prefer explicit factory helpers if present. Otherwise, we try a short list
    of common class/singleton names.

    Failures are surfaced deterministically via :class:`MissingBrowserConfiguration`.
    """

    try:
        from thomas.tools import browser as browser_mod  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise MissingBrowserConfiguration(
            "Browser tool is not available (failed to import thomas.tools.browser).",
            details={"cause": type(exc).__name__},
        ) from None

    for fn_name in (
        "get_default_browser",
        "get_browser",
        "create_browser",
        "default_browser",
    ):
        fn = getattr(browser_mod, fn_name, None)
        if callable(fn):
            try:
                return fn()
            except Exception as exc:
                raise MissingBrowserConfiguration(
                    "Browser is not configured.",
                    details={"cause": type(exc).__name__, "factory": fn_name},
                ) from None

    for cls_name in (
        "BrowserTool",
        "Browser",
        "BrowserClient",
        "LiveBrowser",
    ):
        cls = getattr(browser_mod, cls_name, None)
        if cls is None:
            continue
        try:
            return cls()  # type: ignore[call-arg]
        except TypeError:
            # Constructor requires args — do not guess.
            continue
        except Exception as exc:
            raise MissingBrowserConfiguration(
                "Browser is not configured.",
                details={"cause": type(exc).__name__, "class": cls_name},
            ) from None

    for attr_name in ("browser", "BROWSER", "client", "CLIENT"):
        inst = getattr(browser_mod, attr_name, None)
        if inst is not None:
            return inst

    raise MissingBrowserConfiguration(
        "Browser is not configured.",
        details={"cause": "not_found"},
    )


_NAVIGATE_METHODS: tuple[str, ...] = (
    "navigate",
    "goto",
    "go_to",
    "goTo",
)

_OPEN_METHODS: tuple[str, ...] = (
    "open",
    "open_url",
    "openUrl",
    "open_tab",
    "openTab",
    "new_tab",
    "newTab",
)


async def _perform_async(browser: Any, request: NavigateAndOpenRequest) -> Any:
    """Execute against the provided browser implementation (async)."""

    method_names = _NAVIGATE_METHODS if request.action == "navigate" else _OPEN_METHODS

    # Prefer explicit top-level methods.
    for name in method_names:
        fn = getattr(browser, name, None)
        if callable(fn):
            try:
                return await _call_with_best_effort_args(fn, request)
            except MissingBrowserConfiguration:
                # Signature mismatch, try the next alias.
                continue

    # Nested tab manager pattern: browser.tabs.open(...)
    tabs = getattr(browser, "tabs", None)
    if tabs is not None:
        nested_name = "navigate" if request.action == "navigate" else "open"
        nested = getattr(tabs, nested_name, None)
        if callable(nested):
            return await _call_with_best_effort_args(nested, request)

    # Generic executor interface: run/execute/call/perform(payload)
    for exec_name in ("run", "execute", "call", "perform"):
        fn = getattr(browser, exec_name, None)
        if not callable(fn):
            continue

        payload: dict[str, Any] = {"action": request.action, "url": request.url}
        if request.timeout_ms is not None:
            payload["timeout_ms"] = request.timeout_ms
        if request.profile is not None:
            payload["profile"] = request.profile

        try:
            return await _maybe_await(fn(payload))
        except NavigateAndOpenError:
            raise
        except Exception as exc:
            raise BrowserOperationFailed(
                "Browser operation failed.",
                details={"cause": type(exc).__name__, "executor": exec_name},
            ) from None

    raise MissingBrowserConfiguration(
        "Browser implementation does not support navigate/open.",
        details={"action": request.action},
    )


async def _call_with_best_effort_args(fn: Any, request: NavigateAndOpenRequest) -> Any:
    """Call *fn* with conservative args/kwargs, await if needed."""

    kwargs = _select_supported_kwargs(fn, request)

    # Try keyword url= first when the signature advertises it; otherwise try
    # positional first. We still attempt both forms to tolerate odd signatures.
    try:
        sig = inspect.signature(fn)
        params = sig.parameters
    except (TypeError, ValueError):
        params = {}

    attempts = []
    if "url" in params:
        attempts.append(("kw_url", lambda: fn(url=request.url, **kwargs)))
    attempts.append(("pos_url", lambda: fn(request.url, **kwargs)))
    if "url" not in params:
        # Still try keyword as a fallback.
        attempts.append(("kw_url", lambda: fn(url=request.url, **kwargs)))

    last_type_error: Exception | None = None

    for attempt_name, thunk in attempts:
        try:
            return await _maybe_await(thunk())
        except TypeError as exc:
            last_type_error = exc
            continue
        except NavigateAndOpenError:
            raise
        except Exception as exc:
            raise BrowserOperationFailed(
                "Browser operation failed.",
                details={"cause": type(exc).__name__, "method": getattr(fn, "__name__", "<callable>")},
            ) from None

    raise MissingBrowserConfiguration(
        "Browser method exists but does not accept the expected arguments.",
        details={
            "cause": type(last_type_error).__name__ if last_type_error else "TypeError",
            "method": getattr(fn, "__name__", "<callable>"),
        },
    )


def _select_supported_kwargs(fn: Any, request: NavigateAndOpenRequest) -> dict[str, Any]:
    """Only pass kwargs the callable appears to accept."""

    try:
        sig = inspect.signature(fn)
        params = sig.parameters
    except (TypeError, ValueError):
        params = {}

    kwargs: dict[str, Any] = {}

    if request.timeout_ms is not None:
        if "timeout_ms" in params:
            kwargs["timeout_ms"] = request.timeout_ms
        elif "timeoutMs" in params:
            kwargs["timeoutMs"] = request.timeout_ms
        elif "timeout" in params:
            kwargs["timeout"] = request.timeout_ms

    if request.profile is not None:
        if "profile" in params:
            kwargs["profile"] = request.profile
        elif "browser_profile" in params:
            kwargs["browser_profile"] = request.profile
        elif "browserProfile" in params:
            kwargs["browserProfile"] = request.profile

    return kwargs


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _extract_tab_id(raw: Any) -> Optional[str]:
    """Best-effort extraction of a tab/page identifier from tool responses."""

    if raw is None:
        return None

    if isinstance(raw, str):
        # Some clients return the id directly.
        return raw

    if isinstance(raw, Mapping):
        for key in ("tab_id", "tabId", "page_id", "pageId", "target_id", "targetId", "id"):
            val = raw.get(key)
            if isinstance(val, str) and val:
                return val

    return None


def _json_safe(value: Any, *, _depth: int = 0) -> Any:
    """Convert arbitrary objects to JSON-safe structures.

    This intentionally avoids calling ``repr()`` on unknown objects because that
    often contains non-deterministic memory addresses.
    """

    if _depth > 6:
        return {"type": "truncated"}

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return {str(k): _json_safe(v, _depth=_depth + 1) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_json_safe(v, _depth=_depth + 1) for v in value]

    return {"type": type(value).__name__}
