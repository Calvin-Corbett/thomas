from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass, field
from enum import Enum
from types import ModuleType
from typing import Any, Callable, Mapping


# ---------------------------------------------------------------------------
# Public contracts
# ---------------------------------------------------------------------------


class ChannelLoginErrorCode(str, Enum):
    """Stable, machine-readable error codes for channel login."""

    INVALID_INPUT = "invalid_input"
    UNKNOWN_CHANNEL = "unknown_channel"
    LOGIN_UNAVAILABLE = "login_unavailable"
    MISSING_CONFIG = "missing_config"
    EXTERNAL_FAILURE = "external_failure"


@dataclass(frozen=True)
class ChannelLoginRequest:
    """Inputs for a channel login attempt.

    `params` can carry any channel-specific flags (e.g., tokens, paths).
    The login runner will attempt to pass matching keys into a channel's
    integration login entrypoint, if that entrypoint accepts them.
    """

    channel: str
    params: Mapping[str, Any] = field(default_factory=dict)
    non_interactive: bool = False
    timeout_s: float | None = None


@dataclass(frozen=True)
class ChannelLoginErrorInfo:
    code: ChannelLoginErrorCode
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelLoginResult:
    ok: bool
    channel: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)
    error: ChannelLoginErrorInfo | None = None


def channel_login_result_to_dict(result: ChannelLoginResult) -> dict[str, Any]:
    """Convert a result to JSON-serializable primitives."""
    payload: dict[str, Any] = {
        "ok": result.ok,
        "channel": result.channel,
        "message": result.message,
        "details": dict(result.details) if result.details else {},
    }
    if result.error is not None:
        payload["error"] = {
            "code": result.error.code.value,
            "message": result.error.message,
            "details": dict(result.error.details) if result.error.details else {},
        }
    return payload


# ---------------------------------------------------------------------------
# Internal exceptions (used for deterministic mapping)
# ---------------------------------------------------------------------------


class _ChannelLoginFailure(Exception):
    def __init__(
        self,
        *,
        code: ChannelLoginErrorCode,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class _MissingChannelConfig(_ChannelLoginFailure):
    def __init__(self, channel: str, missing: list[str]) -> None:
        super().__init__(
            code=ChannelLoginErrorCode.MISSING_CONFIG,
            message=f"Missing configuration for channel '{channel}'.",
            details={"missing": sorted(missing)},
        )


class _UnknownChannel(_ChannelLoginFailure):
    def __init__(self, channel: str) -> None:
        super().__init__(
            code=ChannelLoginErrorCode.UNKNOWN_CHANNEL,
            message=f"Unknown channel '{channel}'.",
            details={},
        )


class _LoginUnavailable(_ChannelLoginFailure):
    def __init__(self, channel: str) -> None:
        super().__init__(
            code=ChannelLoginErrorCode.LOGIN_UNAVAILABLE,
            message=f"Channel '{channel}' does not support interactive login.",
            details={},
        )


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------


def channel_login(request: ChannelLoginRequest) -> ChannelLoginResult:
    """Attempt to authenticate/link a messaging channel account.

    This command is intentionally integration-driven:
    * It loads `thomas.integrations.<channel>`
    * It finds a login entrypoint
    * It calls it with supported args from the request

    All failures are mapped to deterministic `ChannelLoginErrorCode` values.
    """
    channel = _normalize_channel_name(request.channel)
    if not channel:
        return _failure(
            channel="",
            code=ChannelLoginErrorCode.INVALID_INPUT,
            message="Channel name is required.",
            details={},
        )

    try:
        module = _load_integration_module(channel)
        raw = _invoke_integration_login(module, channel, request)
        details, message = _normalize_login_return(channel, raw)
        return ChannelLoginResult(
            ok=True,
            channel=channel,
            message=message,
            details=details,
            error=None,
        )
    except _ChannelLoginFailure as exc:
        return _failure(channel=channel, code=exc.code, message=exc.message, details=exc.details)
    except Exception as exc:  # pragma: no cover
        # Last-resort catch to avoid leaking stack traces in normal runs.
        return _failure(
            channel=channel,
            code=ChannelLoginErrorCode.EXTERNAL_FAILURE,
            message=f"Channel '{channel}' login failed due to an external error.",
            details={"exception": exc.__class__.__name__},
        )


def _failure(*, channel: str, code: ChannelLoginErrorCode, message: str, details: Mapping[str, Any]) -> ChannelLoginResult:
    return ChannelLoginResult(
        ok=False,
        channel=channel,
        message=message,
        details={},
        error=ChannelLoginErrorInfo(code=code, message=message, details=details),
    )


def _normalize_channel_name(channel: str) -> str:
    return channel.strip().lower()


def _load_integration_module(channel: str) -> ModuleType:
    module_name = f"thomas.integrations.{channel}"
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        # Only treat as unknown channel when the missing module is the channel module itself.
        if getattr(exc, "name", None) == module_name:
            raise _UnknownChannel(channel) from exc
        raise _ChannelLoginFailure(
            code=ChannelLoginErrorCode.EXTERNAL_FAILURE,
            message=f"Failed to import integration for channel '{channel}'.",
            details={"exception": exc.__class__.__name__},
        ) from exc


def _invoke_integration_login(module: ModuleType, channel: str, request: ChannelLoginRequest) -> Any:
    # Preferred function entrypoints.
    for name in ("login", "channel_login", "login_channel", "authenticate"):
        candidate = getattr(module, name, None)
        if callable(candidate):
            return _call_login(candidate, channel, request)

    login_class = _find_login_class(module, channel)
    if login_class is None:
        raise _LoginUnavailable(channel)

    instance = _instantiate_with_request(login_class, channel, request)
    login_method = getattr(instance, "login")
    return _call_login(login_method, channel, request)


def _find_login_class(module: ModuleType, channel: str) -> type | None:
    preferred_class_names = (
        f"{_camel_case(channel)}Integration",
        f"{_camel_case(channel)}Client",
        f"{_camel_case(channel)}Connector",
        "Integration",
        "Client",
        "Connector",
    )
    for class_name in preferred_class_names:
        candidate = getattr(module, class_name, None)
        if inspect.isclass(candidate) and hasattr(candidate, "login"):
            return candidate

    for candidate in module.__dict__.values():
        if inspect.isclass(candidate) and hasattr(candidate, "login"):
            return candidate

    return None


def _instantiate_with_request(cls: type, channel: str, request: ChannelLoginRequest) -> Any:
    """Instantiate a class, best-effort, using request params when available."""
    try:
        sig = inspect.signature(cls)
    except (TypeError, ValueError):
        return cls()

    kwargs = _build_kwargs_from_request(sig, channel, request)
    missing = _missing_required_kwargs(sig, kwargs)
    if missing:
        raise _MissingChannelConfig(channel, missing)

    try:
        return cls(**kwargs)
    except TypeError as exc:
        # If kwargs were empty and instantiation still failed, treat as missing config;
        # otherwise treat as external failure.
        if not kwargs:
            raise _MissingChannelConfig(channel, missing=["<constructor-args>"]) from exc
        raise _ChannelLoginFailure(
            code=ChannelLoginErrorCode.EXTERNAL_FAILURE,
            message=f"Failed to initialize integration for channel '{channel}'.",
            details={"exception": exc.__class__.__name__},
        ) from exc


def _call_login(callable_obj: Callable[..., Any], channel: str, request: ChannelLoginRequest) -> Any:
    sig = inspect.signature(callable_obj)
    kwargs = _build_kwargs_from_request(sig, channel, request)

    missing = _missing_required_kwargs(sig, kwargs)
    if missing:
        raise _MissingChannelConfig(channel, missing)

    try:
        return callable_obj(**kwargs)
    except _ChannelLoginFailure:
        raise
    except Exception as exc:
        raise _ChannelLoginFailure(
            code=ChannelLoginErrorCode.EXTERNAL_FAILURE,
            message=f"Channel '{channel}' login failed due to an external error.",
            details={"exception": exc.__class__.__name__},
        ) from exc


def _build_kwargs_from_request(sig: inspect.Signature, channel: str, request: ChannelLoginRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}

    for name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if name in ("request", "req"):
            kwargs[name] = request
            continue
        if name in ("channel", "channel_name"):
            kwargs[name] = channel
            continue
        if name in ("params", "options"):
            kwargs[name] = request.params
            continue
        if name == "non_interactive":
            kwargs[name] = request.non_interactive
            continue
        if name == "interactive":
            kwargs[name] = not request.non_interactive
            continue
        if name in ("timeout", "timeout_s", "timeout_seconds") and request.timeout_s is not None:
            kwargs[name] = request.timeout_s
            continue
        if name in request.params:
            kwargs[name] = request.params[name]
            continue

    return kwargs


def _missing_required_kwargs(sig: inspect.Signature, kwargs: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    for name, param in sig.parameters.items():
        if name in kwargs:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        # Positional-only parameters can't be satisfied safely here.
        missing.append(name)
    return sorted(missing)


def _normalize_login_return(channel: str, raw: Any) -> tuple[dict[str, Any], str]:
    if raw is None:
        return {}, f"Channel '{channel}' login succeeded."
    if isinstance(raw, str):
        return {}, raw
    if isinstance(raw, Mapping):
        details = {str(k): v for k, v in raw.items()}
        message = str(details.get("message", f"Channel '{channel}' login succeeded."))
        # Don't duplicate "message" inside details for JSON output unless it contains more.
        details_no_msg = {k: v for k, v in details.items() if k != "message"}
        return details_no_msg, message
    if isinstance(raw, bool):
        return {"result": raw}, f"Channel '{channel}' login {'succeeded' if raw else 'failed'}."
    # Best-effort JSON friendliness.
    return {"result": str(raw)}, f"Channel '{channel}' login succeeded."


def _camel_case(s: str) -> str:
    parts = [p for p in _split_non_alnum(s) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts)


def _split_non_alnum(s: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    for ch in s:
        if ch.isalnum():
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
                cur = []
    if cur:
        out.append("".join(cur))
    return out
