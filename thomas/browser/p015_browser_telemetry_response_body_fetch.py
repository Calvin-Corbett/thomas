"""Browser telemetry response body fetch (P015).

Thomas sometimes records browser *telemetry* (network events). Given a telemetry
request/response identifier (commonly a CDP `requestId`), this module retrieves
the associated response body from the active browser backend.

Design goals
- Thomas-native naming (no OpenClaw surface re-use).
- Clear, typed input/output contracts.
- Deterministic, machine-readable errors.
- Backend-agnostic: works with any backend that can expose a response-body fetch.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol

__all__ = [
    "BrowserTelemetryResponseBodyFetchError",
    "BrowserTelemetryResponseBodyFetchRequest",
    "BrowserTelemetryResponseBodyFetchResult",
    "BrowserTelemetryBackend",
    "fetch_browser_telemetry_response_body",
    "async_fetch_browser_telemetry_response_body",
    "request_json_schema",
    "result_json_schema",
    "error_json_schema",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BrowserTelemetryResponseBodyFetchError(Exception):
    """Deterministic error raised by telemetry response body fetch.

    Attributes:
        code: Stable error code suitable for automation.
        message: Human-readable explanation.
        details: Additional structured context (JSON-serialisable).
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


def error_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "details": {"type": "object"},
        },
        "required": ["code", "message", "details"],
    }


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BrowserTelemetryResponseBodyFetchRequest:
    """Input contract."""

    request_id: str
    max_bytes: int | None = None
    timeout_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def request_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "request_id": {"type": "string", "minLength": 1},
            "max_bytes": {"type": ["integer", "null"], "minimum": 1},
            "timeout_s": {"type": ["number", "null"], "exclusiveMinimum": 0},
        },
        "required": ["request_id"],
    }


@dataclass(frozen=True, slots=True)
class BrowserTelemetryResponseBodyFetchResult:
    """Output contract."""

    request_id: str
    body_base64: str
    body_text: str | None
    content_type: str | None
    url: str | None
    status: int | None
    original_size_bytes: int
    returned_size_bytes: int
    truncated: bool
    original_base64_encoded: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def result_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "request_id": {"type": "string"},
            "body_base64": {"type": "string"},
            "body_text": {"type": ["string", "null"]},
            "content_type": {"type": ["string", "null"]},
            "url": {"type": ["string", "null"]},
            "status": {"type": ["integer", "null"]},
            "original_size_bytes": {"type": "integer", "minimum": 0},
            "returned_size_bytes": {"type": "integer", "minimum": 0},
            "truncated": {"type": "boolean"},
            "original_base64_encoded": {"type": "boolean"},
        },
        "required": [
            "request_id",
            "body_base64",
            "body_text",
            "content_type",
            "url",
            "status",
            "original_size_bytes",
            "returned_size_bytes",
            "truncated",
            "original_base64_encoded",
        ],
    }


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------


class BrowserTelemetryBackend(Protocol):
    """Minimal backend protocol.

    Implementations should return one of:
    - bytes / bytearray
    - str (utf-8 text)
    - Mapping with keys similar to CDP: {"body": str, "base64Encoded": bool}
    - Any of the above wrapped in an awaitable
    """

    def get_response_body(self, request_id: str, *, timeout_s: float | None = None) -> Any: ...


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_browser_telemetry_response_body(
    request: BrowserTelemetryResponseBodyFetchRequest,
    *,
    backend: BrowserTelemetryBackend | None = None,
) -> BrowserTelemetryResponseBodyFetchResult:
    """Synchronous fetch.

    If the backend returns an awaitable and we're not currently inside an event
    loop, this function will execute the awaitable via ``asyncio.run``.

    If called from within an active event loop and the backend is async, a
    deterministic ``invalid_context`` error is raised (use the async API).
    """

    validated = _validate_request(request)
    resolved_backend = backend or _resolve_backend()

    raw = _call_backend(resolved_backend, validated.request_id, validated.timeout_s)
    raw = _maybe_await_sync(raw)

    body_bytes, meta = _normalize_backend_result(raw)
    return _build_result(validated, body_bytes, meta)


async def async_fetch_browser_telemetry_response_body(
    request: BrowserTelemetryResponseBodyFetchRequest,
    *,
    backend: BrowserTelemetryBackend | None = None,
) -> BrowserTelemetryResponseBodyFetchResult:
    """Asynchronous fetch.

    This is safe to call inside an event loop.
    """

    validated = _validate_request(request)
    resolved_backend = backend or _resolve_backend()

    raw = _call_backend(resolved_backend, validated.request_id, validated.timeout_s)
    raw = await _maybe_await_async(raw)

    body_bytes, meta = _normalize_backend_result(raw)
    return _build_result(validated, body_bytes, meta)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_request(req: BrowserTelemetryResponseBodyFetchRequest) -> BrowserTelemetryResponseBodyFetchRequest:
    request_id = _validate_request_id(req.request_id)
    max_bytes = _validate_max_bytes(req.max_bytes)
    timeout_s = _validate_timeout(req.timeout_s)
    return BrowserTelemetryResponseBodyFetchRequest(
        request_id=request_id,
        max_bytes=max_bytes,
        timeout_s=timeout_s,
    )


def _validate_request_id(value: Any) -> str:
    if not isinstance(value, str):
        raise BrowserTelemetryResponseBodyFetchError(
            code="invalid_input",
            message="request_id must be a string.",
            details={"field": "request_id"},
        )
    request_id = value.strip()
    if not request_id:
        raise BrowserTelemetryResponseBodyFetchError(
            code="invalid_input",
            message="request_id must be a non-empty string.",
            details={"field": "request_id"},
        )
    return request_id


def _validate_max_bytes(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise BrowserTelemetryResponseBodyFetchError(
            code="invalid_input",
            message="max_bytes must be an integer.",
            details={"field": "max_bytes"},
        )
    if value <= 0:
        raise BrowserTelemetryResponseBodyFetchError(
            code="invalid_input",
            message="max_bytes must be a positive integer.",
            details={"field": "max_bytes"},
        )
    return value


def _validate_timeout(value: Any) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise BrowserTelemetryResponseBodyFetchError(
            code="invalid_input",
            message="timeout_s must be a number.",
            details={"field": "timeout_s"},
        )
    timeout = float(value)
    if timeout <= 0:
        raise BrowserTelemetryResponseBodyFetchError(
            code="invalid_input",
            message="timeout_s must be > 0.",
            details={"field": "timeout_s"},
        )
    return timeout


# ---------------------------------------------------------------------------
# Backend resolution and calling
# ---------------------------------------------------------------------------


def _resolve_backend() -> BrowserTelemetryBackend:
    """Resolve a browser backend using the existing Thomas runtime.

    This is best-effort and intentionally conservative: if we can't locate a
    backend object that supports the needed capability, we fail deterministically
    with ``missing_config``.
    """

    attempted: list[str] = []
    last_exc: Exception | None = None

    # 1) thomas.cli.live_browser (persistent interactive browser)
    try:
        from thomas.cli import live_browser as live_browser_mod  # type: ignore
    except Exception as e:  # pragma: no cover
        live_browser_mod = None
        last_exc = e

    if live_browser_mod is not None:
        for attr in (
            "get_live_browser",
            "get_browser",
            "get_client",
            "get_live_browser_client",
            "browser",
            "client",
        ):
            attempted.append(f"thomas.cli.live_browser.{attr}")
            try:
                obj = getattr(live_browser_mod, attr)
            except Exception as e:  # pragma: no cover
                last_exc = e
                continue

            try:
                backend_obj = obj() if callable(obj) else obj
            except Exception as e:  # pragma: no cover
                last_exc = e
                continue

            if backend_obj is not None:
                return _BackendAdapter(backend_obj)

    # 2) thomas.tools.browser (tool-based backend)
    try:
        from thomas.tools import browser as browser_tool_mod  # type: ignore
    except Exception as e:  # pragma: no cover
        browser_tool_mod = None
        last_exc = e

    if browser_tool_mod is not None:
        for fn_name in ("get_browser_tool", "get_default_browser_tool", "get_browser", "get_tool"):
            attempted.append(f"thomas.tools.browser.{fn_name}")
            fn = getattr(browser_tool_mod, fn_name, None)
            if not callable(fn):
                continue
            try:
                backend_obj = fn()
            except Exception as e:  # pragma: no cover
                last_exc = e
                continue
            if backend_obj is not None:
                return _BackendAdapter(backend_obj)

        tool_cls = getattr(browser_tool_mod, "BrowserTool", None)
        if tool_cls is not None:
            for ctor_name in ("from_default_config", "from_default", "from_config", "from_env"):
                attempted.append(f"thomas.tools.browser.BrowserTool.{ctor_name}")
                ctor = getattr(tool_cls, ctor_name, None)
                if not callable(ctor):
                    continue
                try:
                    backend_obj = ctor()
                except Exception as e:  # pragma: no cover
                    last_exc = e
                    continue
                return _BackendAdapter(backend_obj)

            attempted.append("thomas.tools.browser.BrowserTool")
            try:
                backend_obj = tool_cls()
            except Exception as e:  # pragma: no cover
                last_exc = e
            else:
                return _BackendAdapter(backend_obj)

    details: dict[str, Any] = {"attempted": attempted}
    if last_exc is not None:
        details["last_error"] = {"type": type(last_exc).__name__, "message": str(last_exc)}

    raise BrowserTelemetryResponseBodyFetchError(
        code="missing_config",
        message="No browser backend is configured or running.",
        details=details,
    )


def _call_backend(backend: BrowserTelemetryBackend, request_id: str, timeout_s: float | None) -> Any:
    try:
        try:
            return backend.get_response_body(request_id, timeout_s=timeout_s)
        except TypeError:
            return backend.get_response_body(request_id)
    except BrowserTelemetryResponseBodyFetchError:
        raise
    except Exception as e:
        raise BrowserTelemetryResponseBodyFetchError(
            code="external_failure",
            message="Browser backend failed while fetching response body.",
            details={"cause_type": type(e).__name__, "cause_message": str(e)},
        ) from None


def _maybe_await_sync(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    # We're inside an event loop but this is the synchronous API. Best-effort
    # cleanup to avoid "coroutine was never awaited" warnings.
    close = getattr(value, "close", None)
    if callable(close):
        try:
            close()
        except (RuntimeError, AttributeError):
            pass

    raise BrowserTelemetryResponseBodyFetchError(
        code="invalid_context",
        message="Sync fetch cannot await inside an active event loop. Use async_fetch_browser_telemetry_response_body.",
        details={},
    )


async def _maybe_await_async(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    return await value


# ---------------------------------------------------------------------------
# Normalisation & result building
# ---------------------------------------------------------------------------


def _normalize_backend_result(raw: Any) -> tuple[bytes, dict[str, Any]]:
    meta: dict[str, Any] = {
        "content_type": None,
        "url": None,
        "status": None,
        "original_base64_encoded": False,
    }

    if isinstance(raw, (bytes, bytearray)):
        return (bytes(raw), meta)

    if isinstance(raw, str):
        return (raw.encode("utf-8"), meta)

    if isinstance(raw, Mapping):
        body = raw.get("body", raw.get("data"))
        if body is None:
            raise BrowserTelemetryResponseBodyFetchError(
                code="external_failure",
                message="Browser backend returned a mapping without a 'body' field.",
                details={"keys": sorted([str(k) for k in raw.keys()])},
            )

        base64_encoded = bool(raw.get("base64Encoded") or raw.get("base64_encoded"))
        meta["original_base64_encoded"] = base64_encoded

        meta["content_type"] = raw.get("contentType") or raw.get("mimeType") or raw.get("content_type")
        meta["url"] = raw.get("url")

        status = raw.get("status")
        try:
            meta["status"] = int(status) if status is not None else None
        except (ValueError, TypeError):
            meta["status"] = None

        if isinstance(body, (bytes, bytearray)):
            return (bytes(body), meta)

        if not isinstance(body, str):
            raise BrowserTelemetryResponseBodyFetchError(
                code="external_failure",
                message="Browser backend returned a non-string body value.",
                details={"body_type": type(body).__name__},
            )

        if base64_encoded:
            try:
                return (base64.b64decode(body), meta)
            except Exception as e:
                raise BrowserTelemetryResponseBodyFetchError(
                    code="external_failure",
                    message="Browser backend returned an invalid base64 body.",
                    details={"cause_type": type(e).__name__, "cause_message": str(e)},
                ) from None

        return (body.encode("utf-8"), meta)

    raise BrowserTelemetryResponseBodyFetchError(
        code="external_failure",
        message="Browser backend returned an unsupported response body type.",
        details={"type": type(raw).__name__},
    )


def _build_result(
    request: BrowserTelemetryResponseBodyFetchRequest, body_bytes: bytes, meta: Mapping[str, Any]
) -> BrowserTelemetryResponseBodyFetchResult:
    original_size = len(body_bytes)

    returned_bytes = body_bytes
    truncated = False
    if request.max_bytes is not None and len(returned_bytes) > request.max_bytes:
        returned_bytes = returned_bytes[: request.max_bytes]
        truncated = True

    returned_size = len(returned_bytes)

    try:
        body_text = returned_bytes.decode("utf-8")
    except UnicodeDecodeError:
        body_text = None

    return BrowserTelemetryResponseBodyFetchResult(
        request_id=request.request_id,
        body_base64=base64.b64encode(returned_bytes).decode("ascii"),
        body_text=body_text,
        content_type=_clean_str(meta.get("content_type")),
        url=_clean_str(meta.get("url")),
        status=meta.get("status") if isinstance(meta.get("status"), int) else None,
        original_size_bytes=original_size,
        returned_size_bytes=returned_size,
        truncated=truncated,
        original_base64_encoded=bool(meta.get("original_base64_encoded", False)),
    )


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v if v else None
    return str(value)


# ---------------------------------------------------------------------------
# Backend adapter
# ---------------------------------------------------------------------------


class _BackendAdapter:
    """Wrap a variety of Thomas browser objects behind the protocol."""

    def __init__(self, obj: Any) -> None:
        self._obj = obj

    def get_response_body(self, request_id: str, *, timeout_s: float | None = None) -> Any:
        for name in (
            "get_response_body",
            "get_network_response_body",
            "get_telemetry_response_body",
            "fetch_response_body",
            "fetch_telemetry_response_body",
            "telemetry_response_body",
        ):
            fn = getattr(self._obj, name, None)
            if callable(fn):
                return _call_with_timeout(fn, request_id=request_id, timeout_s=timeout_s)

        raise BrowserTelemetryResponseBodyFetchError(
            code="unsupported_backend",
            message="The configured browser backend does not support telemetry response body fetch.",
            details={"backend_type": type(self._obj).__name__},
        )


def _call_with_timeout(fn: Any, *, request_id: str, timeout_s: float | None) -> Any:
    """Call backend method while trying a few common timeout conventions."""

    if timeout_s is None:
        return fn(request_id)

    for kwargs in (
        {"request_id": request_id, "timeout_s": timeout_s},
        {"request_id": request_id, "timeout": timeout_s},
        {"request_id": request_id, "timeout_seconds": timeout_s},
    ):
        try:
            return fn(**kwargs)
        except TypeError:
            continue

    for args in (
        (request_id, timeout_s),
        (request_id,),
    ):
        try:
            return fn(*args)
        except TypeError:
            continue

    return fn(request_id)
