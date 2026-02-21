"""Browser lifecycle helpers: start, stop, restart.

Thomas already has browser automation/tooling. This module adds a *lifecycle* layer:
- start: ensure browser is running
- stop: ensure browser is stopped
- restart: stop then start (or call backend restart when available)

Design goals:
- Thomas-native naming (no OpenClaw reuse)
- Small, typed contracts for automation
- Deterministic, machine-readable errors
- Backend-agnostic: adapts existing Thomas browser tooling (live_browser/tools.browser)

This module deliberately does not attempt to expose the full browser API; it is
only about process/session lifecycle.
"""

from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal, Mapping, Protocol, runtime_checkable

BrowserLifecycleAction = Literal["start", "stop", "restart"]


@dataclass(frozen=True, slots=True)
class BrowserLifecycleRequest:
    """Input contract for a browser lifecycle operation."""

    action: str
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class BrowserLifecycleResult:
    """Output contract for a browser lifecycle operation."""

    action: BrowserLifecycleAction
    ok: bool
    state: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["details"] = _coerce_jsonable(payload.get("details", {}))
        return payload


class BrowserLifecycleError(Exception):
    """Deterministic error for browser lifecycle failures."""

    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": _coerce_jsonable(self.details),
            },
        }


@runtime_checkable
class BrowserController(Protocol):
    """Minimal interface expected by this module."""

    def start(self, *, timeout_seconds: float | None = None) -> Any: ...

    def stop(self, *, timeout_seconds: float | None = None) -> Any: ...

    def restart(self, *, timeout_seconds: float | None = None) -> Any: ...


def run_browser_lifecycle(
    request: BrowserLifecycleRequest,
    *,
    controller: Any | None = None,
) -> BrowserLifecycleResult:
    """Run a browser lifecycle operation.

    Raises:
        BrowserLifecycleError: deterministic error with stable code/message.
    """

    action = _normalize_action(request.action)
    timeout_seconds = _normalize_timeout(request.timeout_seconds)

    try:
        raw_ctl = controller or get_default_browser_controller()

        # Allow tests/consumers to pass in loosely-shaped controllers. If the
        # provided object doesn't implement restart, for example, we can still
        # adapt it and provide a stop+start fallback.
        ctl = raw_ctl
        if not isinstance(raw_ctl, BrowserController):
            adapted = _adapt_object(raw_ctl)
            if adapted is None:
                raise BrowserLifecycleError(
                    code="UNSUPPORTED_BACKEND",
                    message="Browser backend does not support the requested lifecycle operation.",
                    details={"backend_type": type(raw_ctl).__name__, "action": action},
                )
            ctl = adapted

        if action == "start":
            details = _safe_details(ctl.start(timeout_seconds=timeout_seconds))
            return BrowserLifecycleResult(action="start", ok=True, state="running", details=details)

        if action == "stop":
            details = _safe_details(ctl.stop(timeout_seconds=timeout_seconds))
            return BrowserLifecycleResult(action="stop", ok=True, state="stopped", details=details)

        details = _safe_details(ctl.restart(timeout_seconds=timeout_seconds))
        return BrowserLifecycleResult(action="restart", ok=True, state="running", details=details)

    except BrowserLifecycleError:
        raise
    except Exception as exc:  # noqa: BLE001 - boundary wrapper
        # Never leak backend exception messages (non-deterministic); only type.
        raise BrowserLifecycleError(
            code="EXTERNAL_FAILURE",
            message=f"Browser {action} failed.",
            details={"exception_type": type(exc).__name__},
        ) from None


def _normalize_action(action: str) -> BrowserLifecycleAction:
    action_norm = (action or "").strip().lower()
    if action_norm not in {"start", "stop", "restart"}:
        raise BrowserLifecycleError(
            code="INVALID_INPUT",
            message="Invalid browser lifecycle action. Expected one of: start, stop, restart.",
            details={"action": action},
        )
    return action_norm  # type: ignore[return-value]


def _normalize_timeout(timeout_seconds: float | None) -> float | None:
    if timeout_seconds is None:
        return None
    if not isinstance(timeout_seconds, (int, float)):
        raise BrowserLifecycleError(
            code="INVALID_INPUT",
            message="timeout_seconds must be a number (seconds).",
            details={"timeout_seconds": repr(timeout_seconds)},
        )
    if timeout_seconds < 0:
        raise BrowserLifecycleError(
            code="INVALID_INPUT",
            message="timeout_seconds must be >= 0.",
            details={"timeout_seconds": timeout_seconds},
        )
    return float(timeout_seconds)


def get_default_browser_controller() -> BrowserController:
    """Resolve a browser controller from existing Thomas tooling.

    Resolution order:
    1) thomas.cli.live_browser
    2) thomas.tools.browser

    Raises:
        BrowserLifecycleError(code="CONFIG_MISSING"): if no usable tooling exists.
    """

    attempted: list[str] = []

    for module_name in ("thomas.cli.live_browser", "thomas.tools.browser"):
        attempted.append(module_name)
        module = _try_import(module_name)
        if module is None:
            continue
        controller = _adapt_from_module(module)
        if controller is not None:
            return controller

    raise BrowserLifecycleError(
        code="CONFIG_MISSING",
        message="Browser tooling is not available (missing configuration or dependencies).",
        details={"attempted_modules": attempted},
    )


def _try_import(module_name: str):
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def _adapt_from_module(module: Any) -> BrowserController | None:
    """Try to obtain a controller object from a module, then adapt it."""

    # Common patterns across projects/codebases:
    # - module.get_live_browser() -> controller
    # - module.get_browser() -> controller
    # - module.get_controller() -> controller
    # - module.get() -> controller
    # - module.browser / module.live_browser -> controller instance
    # - module.BrowserTool() / module.BrowserManager() / module.LiveBrowser() -> controller instance
    candidates: list[Any] = []

    for attr in (
        "get_live_browser",
        "get_browser",
        "get_controller",
        "get_browser_controller",
        "get",
        "browser",
        "live_browser",
    ):
        if hasattr(module, attr):
            candidates.append(getattr(module, attr))

    for attr in ("BrowserTool", "BrowserManager", "LiveBrowser", "Browser"):
        if hasattr(module, attr):
            candidates.append(getattr(module, attr))

    for candidate in candidates:
        try:
            obj = candidate() if callable(candidate) else candidate
        except TypeError:
            # Constructor signature mismatch; skip deterministically.
            continue
        except Exception:
            # Tooling can raise on missing config/deps; treat as "not usable".
            continue
        if obj is None:
            continue
        adapted = _adapt_object(obj)
        if adapted is not None:
            return adapted

    return None


def _adapt_object(obj: Any) -> BrowserController | None:
    # If it already matches the protocol, we're done.
    if isinstance(obj, BrowserController):
        return obj

    # Otherwise, only accept it if it has at least one relevant callable.
    if not _has_any_lifecycle_method(obj):
        return None

    return _ObjectBrowserController(obj)


def _has_any_lifecycle_method(obj: Any) -> bool:
    for name in (*_START_METHODS, *_STOP_METHODS, *_RESTART_METHODS):
        fn = getattr(obj, name, None)
        if callable(fn):
            return True
    return False


class _ObjectBrowserController:
    """Adapter wrapper around a backend object with various method names."""

    def __init__(self, obj: Any):
        self._obj = obj

    def start(self, *, timeout_seconds: float | None = None) -> Any:
        return _invoke(self._obj, _START_METHODS, timeout_seconds)

    def stop(self, *, timeout_seconds: float | None = None) -> Any:
        return _invoke(self._obj, _STOP_METHODS, timeout_seconds)

    def restart(self, *, timeout_seconds: float | None = None) -> Any:
        # Prefer native restart when available.
        try:
            return _invoke(self._obj, _RESTART_METHODS, timeout_seconds)
        except BrowserLifecycleError as err:
            if err.code != "UNSUPPORTED_BACKEND":
                raise

        # Fallback: stop then start.
        self.stop(timeout_seconds=timeout_seconds)
        return self.start(timeout_seconds=timeout_seconds)


_START_METHODS = ("start", "launch", "open", "ensure_started", "ensure_running", "ensure_open")
_STOP_METHODS = ("stop", "close", "shutdown", "terminate", "ensure_stopped", "ensure_closed")
_RESTART_METHODS = ("restart", "reset")


def _invoke(obj: Any, method_names: Iterable[str], timeout_seconds: float | None) -> Any:
    for name in method_names:
        fn = getattr(obj, name, None)
        if not callable(fn):
            continue
        return _call_with_optional_timeout(fn, timeout_seconds)

    raise BrowserLifecycleError(
        code="UNSUPPORTED_BACKEND",
        message="Browser backend does not support the requested lifecycle operation.",
        details={"backend_type": type(obj).__name__},
    )


def _call_with_optional_timeout(fn: Any, timeout_seconds: float | None) -> Any:
    if timeout_seconds is None:
        return fn()

    # Try a couple of common kwarg names; fall back to no-arg call.
    for kw in ("timeout_seconds", "timeout", "wait_seconds", "wait"):
        try:
            return fn(**{kw: timeout_seconds})
        except TypeError:
            continue
    return fn()


def _safe_details(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    return {"result": _coerce_jsonable(value)}


def _coerce_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _coerce_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce_jsonable(v) for v in value]
    return repr(value)
