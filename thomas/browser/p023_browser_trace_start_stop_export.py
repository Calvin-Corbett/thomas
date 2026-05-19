"""
Browser tracing: start, stop, and export.

This module is intentionally "Thomas-native" (no OpenClaw naming reuse). It provides:

- Explicit input/output contracts (dataclasses).
- Deterministic, machine-readable errors (BrowserTraceError with stable codes).
- A small in-process registry to track trace state per browser context.

It is designed for Playwright's BrowserContext tracing API:

    context.tracing.start(...)
    context.tracing.stop(path=...)

Callers may pass:
- a Playwright BrowserContext (has `.tracing`)
- a Page-like object (has `.context`)
- a wrapper exposing `.page.context` or `.context`
- a mapping/dict containing `context` or `page`

Export behavior:
- If export `path` is a directory, the trace will be exported as
  `<dir>/browser_trace_<trace_id>.zip`.
- If export `path` has no file extension, `.zip` is appended.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class BrowserTraceErrorCode(str, Enum):
    """Stable error codes for browser tracing operations."""

    MISSING_SESSION = "BROWSER_TRACE_MISSING_SESSION"
    TARGET_NOT_TRACEABLE = "BROWSER_TRACE_TARGET_NOT_TRACEABLE"
    ALREADY_STARTED = "BROWSER_TRACE_ALREADY_STARTED"
    NOT_STARTED = "BROWSER_TRACE_NOT_STARTED"
    ALREADY_STOPPED = "BROWSER_TRACE_ALREADY_STOPPED"
    NOT_STOPPED = "BROWSER_TRACE_NOT_STOPPED"
    START_FAILED = "BROWSER_TRACE_START_FAILED"
    STOP_FAILED = "BROWSER_TRACE_STOP_FAILED"
    TRACE_FILE_MISSING = "BROWSER_TRACE_FILE_MISSING"
    INVALID_EXPORT_PATH = "BROWSER_TRACE_INVALID_EXPORT_PATH"
    INVALID_INPUT = "BROWSER_TRACE_INVALID_INPUT"
    EXPORT_FAILED = "BROWSER_TRACE_EXPORT_FAILED"
    ASYNC_API_UNSUPPORTED = "BROWSER_TRACE_ASYNC_API_UNSUPPORTED"


@dataclass(frozen=True)
class BrowserTraceStartInput:
    screenshots: bool = True
    snapshots: bool = True
    sources: bool = True
    title: str | None = None


@dataclass(frozen=True)
class BrowserTraceStartOutput:
    trace_id: str
    status: str = "started"


@dataclass(frozen=True)
class BrowserTraceStopInput:
    # Reserved for future expansion (e.g., stop a specific trace_id).
    pass


@dataclass(frozen=True)
class BrowserTraceStopOutput:
    trace_id: str
    temp_path: str
    status: str = "stopped"


@dataclass(frozen=True)
class BrowserTraceExportInput:
    path: str
    overwrite: bool = False


@dataclass(frozen=True)
class BrowserTraceExportOutput:
    trace_id: str
    exported_path: str
    bytes_written: int
    status: str = "exported"


@dataclass
class _TraceState:
    trace_id: str
    status: str  # started | stopped | exported
    started_at: float
    options: BrowserTraceStartInput
    temp_path: Path | None = None
    exported_path: Path | None = None


class BrowserTraceError(RuntimeError):
    """Deterministic error for browser trace operations."""

    def __init__(
        self,
        code: BrowserTraceErrorCode | str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.code: str = code.value if isinstance(code, BrowserTraceErrorCode) else str(code)
        self.message: str = message
        self.details: dict[str, Any] = details or {}
        self.__cause__ = cause
        super().__init__(f"{self.code}: {self.message}")

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


def _is_coroutine_like(obj: Any) -> bool:
    # Avoid importing asyncio at module import time.
    return hasattr(obj, "__await__")


def _call_sync(method: Any, *args: Any, **kwargs: Any) -> None:
    """Call a tracing method in a sync context, refusing async Playwright APIs."""
    result = method(*args, **kwargs)
    if _is_coroutine_like(result):
        raise BrowserTraceError(
            BrowserTraceErrorCode.ASYNC_API_UNSUPPORTED,
            "Async Playwright tracing API detected in a sync call.",
            details={"method": getattr(method, "__name__", str(method))},
        )


async def _call_async(method: Any, *args: Any, **kwargs: Any) -> None:
    """Call a tracing method in an async context, awaiting if needed."""
    result = method(*args, **kwargs)
    if _is_coroutine_like(result):
        await result


def _resolve_browser_context(target: Any, *, _depth: int = 0) -> Any:
    """Best-effort extraction of a Playwright BrowserContext-ish object."""
    if target is None:
        return None
    if _depth > 4:
        return None

    # Direct BrowserContext-like.
    if hasattr(target, "tracing"):
        return target

    # Dict-like session objects.
    if isinstance(target, Mapping):
        for key in ("context", "browser_context", "ctx"):
            if key in target:
                ctx = _resolve_browser_context(target.get(key), _depth=_depth + 1)
                if ctx is not None:
                    return ctx
        for key in ("page", "current_page"):
            if key in target:
                page = target.get(key)
                ctx = getattr(page, "context", None)
                if ctx is not None and hasattr(ctx, "tracing"):
                    return ctx
        for key in ("session", "browser", "live_browser"):
            if key in target:
                ctx = _resolve_browser_context(target.get(key), _depth=_depth + 1)
                if ctx is not None:
                    return ctx

    # Wrapper exposing .context
    ctx = getattr(target, "context", None)
    if ctx is not None and hasattr(ctx, "tracing"):
        return ctx

    # Wrapper exposing .page.context
    page = getattr(target, "page", None)
    if page is not None:
        page_ctx = getattr(page, "context", None)
        if page_ctx is not None and hasattr(page_ctx, "tracing"):
            return page_ctx

    # Wrapper exposing .browser or .session
    for attr in ("browser", "session", "live_browser"):
        obj = getattr(target, attr, None)
        if obj is not None:
            ctx = _resolve_browser_context(obj, _depth=_depth + 1)
            if ctx is not None:
                return ctx

    return None


def _default_temp_dir() -> Path:
    base = Path(os.environ.get("THOMAS_BROWSER_TRACE_DIR", tempfile.gettempdir()))
    return base / "thomas_browser_traces"


def _ensure_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        raise BrowserTraceError(
            BrowserTraceErrorCode.EXPORT_FAILED,
            "Failed to create directory.",
            details={"path": str(path)},
            cause=e,
        ) from e


def _validate_and_resolve_export_path(path_str: str, *, trace_id: str, overwrite: bool) -> Path:
    if not path_str or not str(path_str).strip():
        raise BrowserTraceError(BrowserTraceErrorCode.INVALID_EXPORT_PATH, "Export path is required.")

    raw = str(path_str)
    p = Path(raw).expanduser()

    # Treat as directory if:
    # - it exists and is a directory, OR
    # - the raw string ends with a path separator (user intent: directory)
    if (p.exists() and p.is_dir()) or raw.endswith(("/", os.sep)):
        _ensure_dir(p)
        p = p / f"browser_trace_{trace_id}.zip"

    # If there is no suffix, append .zip for nicer UX / determinism.
    if p.suffix == "":
        p = p.with_suffix(".zip")

    # Prevent accidental directory overwrite.
    if p.exists() and p.is_dir():
        raise BrowserTraceError(
            BrowserTraceErrorCode.INVALID_EXPORT_PATH,
            "Export path points to a directory; expected a file path.",
            details={"path": str(p)},
        )

    # Overwrite handling.
    if p.exists() and not overwrite:
        raise BrowserTraceError(
            BrowserTraceErrorCode.INVALID_EXPORT_PATH,
            "Export path already exists. Use overwrite=true to replace it.",
            details={"path": str(p)},
        )

    _ensure_dir(p.parent)
    return p


def _safe_tracing_start(ctx: Any, params: BrowserTraceStartInput) -> None:
    """Call Playwright tracing.start with graceful fallback for version differences."""
    kwargs: dict[str, Any] = {
        "screenshots": params.screenshots,
        "snapshots": params.snapshots,
        "sources": params.sources,
    }
    if params.title is not None:
        kwargs["title"] = params.title

    try:
        _call_sync(ctx.tracing.start, **kwargs)
        return
    except TypeError as e:
        # Retry without optional args (e.g., title) for older Playwright versions.
        base_kwargs = {
            "screenshots": params.screenshots,
            "snapshots": params.snapshots,
            "sources": params.sources,
        }
        try:
            _call_sync(ctx.tracing.start, **base_kwargs)
            return
        except Exception as e2:  # noqa: BLE001
            raise BrowserTraceError(
                BrowserTraceErrorCode.START_FAILED,
                "Failed to start browser tracing (Playwright API mismatch).",
                details={"primary_error": repr(e), "retry_error": repr(e2)},
                cause=e2,
            ) from e2
    except BrowserTraceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise BrowserTraceError(
            BrowserTraceErrorCode.START_FAILED,
            "Failed to start browser tracing.",
            details={"cause": repr(e)},
            cause=e,
        ) from e


async def _safe_tracing_start_async(ctx: Any, params: BrowserTraceStartInput) -> None:
    kwargs: dict[str, Any] = {
        "screenshots": params.screenshots,
        "snapshots": params.snapshots,
        "sources": params.sources,
    }
    if params.title is not None:
        kwargs["title"] = params.title

    try:
        await _call_async(ctx.tracing.start, **kwargs)
        return
    except TypeError as e:
        base_kwargs = {
            "screenshots": params.screenshots,
            "snapshots": params.snapshots,
            "sources": params.sources,
        }
        try:
            await _call_async(ctx.tracing.start, **base_kwargs)
            return
        except Exception as e2:  # noqa: BLE001
            raise BrowserTraceError(
                BrowserTraceErrorCode.START_FAILED,
                "Failed to start browser tracing (Playwright API mismatch).",
                details={"primary_error": repr(e), "retry_error": repr(e2)},
                cause=e2,
            ) from e2
    except BrowserTraceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise BrowserTraceError(
            BrowserTraceErrorCode.START_FAILED,
            "Failed to start browser tracing.",
            details={"cause": repr(e)},
            cause=e,
        ) from e


def _safe_tracing_stop(ctx: Any, temp_path: Path) -> None:
    """Call Playwright tracing.stop with graceful fallback for signature differences."""
    path_str = str(temp_path)
    try:
        _call_sync(ctx.tracing.stop, path=path_str)
        return
    except TypeError as e:
        # Some versions may require positional argument.
        try:
            _call_sync(ctx.tracing.stop, path_str)
            return
        except Exception as e2:  # noqa: BLE001
            raise BrowserTraceError(
                BrowserTraceErrorCode.STOP_FAILED,
                "Failed to stop browser tracing (Playwright API mismatch).",
                details={"primary_error": repr(e), "retry_error": repr(e2)},
                cause=e2,
            ) from e2
    except BrowserTraceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise BrowserTraceError(
            BrowserTraceErrorCode.STOP_FAILED,
            "Failed to stop browser tracing.",
            details={"cause": repr(e)},
            cause=e,
        ) from e


async def _safe_tracing_stop_async(ctx: Any, temp_path: Path) -> None:
    path_str = str(temp_path)
    try:
        await _call_async(ctx.tracing.stop, path=path_str)
        return
    except TypeError as e:
        try:
            await _call_async(ctx.tracing.stop, path_str)
            return
        except Exception as e2:  # noqa: BLE001
            raise BrowserTraceError(
                BrowserTraceErrorCode.STOP_FAILED,
                "Failed to stop browser tracing (Playwright API mismatch).",
                details={"primary_error": repr(e), "retry_error": repr(e2)},
                cause=e2,
            ) from e2
    except BrowserTraceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise BrowserTraceError(
            BrowserTraceErrorCode.STOP_FAILED,
            "Failed to stop browser tracing.",
            details={"cause": repr(e)},
            cause=e,
        ) from e


class BrowserTraceRegistry:
    """In-process trace state for a given Playwright BrowserContext."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[int, _TraceState] = {}

    def _key_for(self, context: Any) -> int:
        return id(context)

    def get_state(self, target: Any) -> _TraceState | None:
        ctx = _resolve_browser_context(target)
        if ctx is None:
            return None
        with self._lock:
            return self._states.get(self._key_for(ctx))

    def start(self, target: Any, params: BrowserTraceStartInput) -> BrowserTraceStartOutput:
        ctx = _resolve_browser_context(target)
        if ctx is None:
            raise BrowserTraceError(
                BrowserTraceErrorCode.TARGET_NOT_TRACEABLE,
                "No trace-capable browser context found. This command must run against an active browser session.",
            )

        key = self._key_for(ctx)
        with self._lock:
            existing = self._states.get(key)
            if existing and existing.status == "started":
                raise BrowserTraceError(
                    BrowserTraceErrorCode.ALREADY_STARTED,
                    "A trace is already running for this browser context.",
                    details={"trace_id": existing.trace_id},
                )
            trace_id = str(uuid4())
            self._states[key] = _TraceState(
                trace_id=trace_id,
                status="started",
                started_at=time.time(),
                options=params,
            )

        try:
            _safe_tracing_start(ctx, params)
        except BrowserTraceError as e:
            with self._lock:
                self._states.pop(key, None)
            raise e

        return BrowserTraceStartOutput(trace_id=trace_id)

    async def start_async(self, target: Any, params: BrowserTraceStartInput) -> BrowserTraceStartOutput:
        ctx = _resolve_browser_context(target)
        if ctx is None:
            raise BrowserTraceError(
                BrowserTraceErrorCode.TARGET_NOT_TRACEABLE,
                "No trace-capable browser context found. This command must run against an active browser session.",
            )

        key = self._key_for(ctx)
        with self._lock:
            existing = self._states.get(key)
            if existing and existing.status == "started":
                raise BrowserTraceError(
                    BrowserTraceErrorCode.ALREADY_STARTED,
                    "A trace is already running for this browser context.",
                    details={"trace_id": existing.trace_id},
                )
            trace_id = str(uuid4())
            self._states[key] = _TraceState(
                trace_id=trace_id,
                status="started",
                started_at=time.time(),
                options=params,
            )

        try:
            await _safe_tracing_start_async(ctx, params)
        except BrowserTraceError as e:
            with self._lock:
                self._states.pop(key, None)
            raise e

        return BrowserTraceStartOutput(trace_id=trace_id)

    def stop(self, target: Any, params: BrowserTraceStopInput | None = None) -> BrowserTraceStopOutput:
        _ = params  # reserved for future use
        ctx = _resolve_browser_context(target)
        if ctx is None:
            raise BrowserTraceError(
                BrowserTraceErrorCode.TARGET_NOT_TRACEABLE,
                "No trace-capable browser context found. This command must run against an active browser session.",
            )

        key = self._key_for(ctx)
        with self._lock:
            state = self._states.get(key)
            if not state:
                raise BrowserTraceError(
                    BrowserTraceErrorCode.NOT_STARTED,
                    "No active trace is running for this browser context.",
                )
            if state.status != "started":
                raise BrowserTraceError(
                    BrowserTraceErrorCode.ALREADY_STOPPED,
                    "Trace is not currently running for this browser context.",
                    details={"trace_id": state.trace_id, "status": state.status},
                )
            trace_id = state.trace_id

        temp_dir = _default_temp_dir()
        _ensure_dir(temp_dir)
        temp_path = temp_dir / f"browser_trace_{trace_id}.zip"

        _safe_tracing_stop(ctx, temp_path)

        if not temp_path.exists():
            raise BrowserTraceError(
                BrowserTraceErrorCode.TRACE_FILE_MISSING,
                "Trace stop succeeded but no trace file was produced.",
                details={"temp_path": str(temp_path)},
            )

        with self._lock:
            state = self._states.get(key)
            if state:
                state.status = "stopped"
                state.temp_path = temp_path

        return BrowserTraceStopOutput(trace_id=trace_id, temp_path=str(temp_path))

    async def stop_async(self, target: Any, params: BrowserTraceStopInput | None = None) -> BrowserTraceStopOutput:
        _ = params
        ctx = _resolve_browser_context(target)
        if ctx is None:
            raise BrowserTraceError(
                BrowserTraceErrorCode.TARGET_NOT_TRACEABLE,
                "No trace-capable browser context found. This command must run against an active browser session.",
            )

        key = self._key_for(ctx)
        with self._lock:
            state = self._states.get(key)
            if not state:
                raise BrowserTraceError(
                    BrowserTraceErrorCode.NOT_STARTED,
                    "No active trace is running for this browser context.",
                )
            if state.status != "started":
                raise BrowserTraceError(
                    BrowserTraceErrorCode.ALREADY_STOPPED,
                    "Trace is not currently running for this browser context.",
                    details={"trace_id": state.trace_id, "status": state.status},
                )
            trace_id = state.trace_id

        temp_dir = _default_temp_dir()
        _ensure_dir(temp_dir)
        temp_path = temp_dir / f"browser_trace_{trace_id}.zip"

        await _safe_tracing_stop_async(ctx, temp_path)

        if not temp_path.exists():
            raise BrowserTraceError(
                BrowserTraceErrorCode.TRACE_FILE_MISSING,
                "Trace stop succeeded but no trace file was produced.",
                details={"temp_path": str(temp_path)},
            )

        with self._lock:
            state = self._states.get(key)
            if state:
                state.status = "stopped"
                state.temp_path = temp_path

        return BrowserTraceStopOutput(trace_id=trace_id, temp_path=str(temp_path))

    def export(self, target: Any, params: BrowserTraceExportInput) -> BrowserTraceExportOutput:
        ctx = _resolve_browser_context(target)
        if ctx is None:
            raise BrowserTraceError(
                BrowserTraceErrorCode.TARGET_NOT_TRACEABLE,
                "No trace-capable browser context found. This command must run against an active browser session.",
            )

        key = self._key_for(ctx)
        with self._lock:
            state = self._states.get(key)
            if not state:
                raise BrowserTraceError(
                    BrowserTraceErrorCode.NOT_STARTED,
                    "No trace has been started for this browser context.",
                )
            if state.status == "started":
                raise BrowserTraceError(
                    BrowserTraceErrorCode.NOT_STOPPED,
                    "Trace is still running. Stop it before exporting.",
                    details={"trace_id": state.trace_id},
                )
            if not state.temp_path:
                raise BrowserTraceError(
                    BrowserTraceErrorCode.TRACE_FILE_MISSING,
                    "No trace file is available to export.",
                    details={"trace_id": state.trace_id},
                )
            trace_id = state.trace_id
            temp_path = state.temp_path

        dest_path = _validate_and_resolve_export_path(params.path, trace_id=trace_id, overwrite=params.overwrite)

        try:
            shutil.copy2(temp_path, dest_path)
            size = dest_path.stat().st_size
        except BrowserTraceError:
            raise
        except Exception as e:  # noqa: BLE001
            raise BrowserTraceError(
                BrowserTraceErrorCode.EXPORT_FAILED,
                "Failed to export trace file.",
                details={"trace_id": trace_id, "from": str(temp_path), "to": str(dest_path), "cause": repr(e)},
                cause=e,
            ) from e

        with self._lock:
            state = self._states.get(key)
            if state:
                state.status = "exported"
                state.exported_path = dest_path

        return BrowserTraceExportOutput(trace_id=trace_id, exported_path=str(dest_path), bytes_written=size)

    def reset_for_tests(self) -> None:
        """Clear registry state. Intended for unit tests only."""
        with self._lock:
            self._states.clear()


DEFAULT_TRACE_REGISTRY = BrowserTraceRegistry()


def start_trace(target: Any, params: BrowserTraceStartInput) -> BrowserTraceStartOutput:
    """Convenience wrapper around the default registry."""
    return DEFAULT_TRACE_REGISTRY.start(target, params)


def stop_trace(target: Any) -> BrowserTraceStopOutput:
    """Convenience wrapper around the default registry."""
    return DEFAULT_TRACE_REGISTRY.stop(target)


def export_trace(target: Any, params: BrowserTraceExportInput) -> BrowserTraceExportOutput:
    """Convenience wrapper around the default registry."""
    return DEFAULT_TRACE_REGISTRY.export(target, params)


# --- JSON Schema helpers (no third-party deps) -----------------------------------


def input_schemas() -> dict[str, Any]:
    """JSON Schemas for automation/routing layers."""
    return {
        "start": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "screenshots": {"type": "boolean", "default": True},
                "snapshots": {"type": "boolean", "default": True},
                "sources": {"type": "boolean", "default": True},
                "title": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            },
        },
        "stop": {"type": "object", "additionalProperties": False, "properties": {}},
        "export": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"path": {"type": "string"}, "overwrite": {"type": "boolean", "default": False}},
            "required": ["path"],
        },
    }


def output_schemas() -> dict[str, Any]:
    """JSON Schemas for automation/routing layers."""
    return {
        "start": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"trace_id": {"type": "string"}, "status": {"type": "string"}},
            "required": ["trace_id", "status"],
        },
        "stop": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "trace_id": {"type": "string"},
                "temp_path": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["trace_id", "temp_path", "status"],
        },
        "export": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "trace_id": {"type": "string"},
                "exported_path": {"type": "string"},
                "bytes_written": {"type": "integer"},
                "status": {"type": "string"},
            },
            "required": ["trace_id", "exported_path", "bytes_written", "status"],
        },
    }


def result_to_json(result: Any) -> str:
    """Serialize a dataclass result to JSON (helper for CLI/tests)."""
    if hasattr(result, "__dataclass_fields__"):
        payload = asdict(result)
    elif isinstance(result, dict):
        payload = result
    else:
        payload = {"value": result}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# --- Compatibility exports for node/router layers --------------------------------


def _coerce_dataclass(cls: Any, payload: Any) -> Any:
    if payload is None:
        return cls()  # type: ignore[call-arg]
    if hasattr(payload, "__dataclass_fields__"):
        return payload
    if isinstance(payload, dict):
        try:
            return cls(**payload)  # type: ignore[misc]
        except TypeError as e:
            raise BrowserTraceError(
                BrowserTraceErrorCode.INVALID_INPUT,
                "Invalid payload fields for trace operation.",
                details={"expected": getattr(cls, "__name__", str(cls)), "cause": str(e)},
                cause=e,
            ) from e
    raise BrowserTraceError(
        BrowserTraceErrorCode.INVALID_INPUT,
        "Invalid payload type for trace operation.",
        details={"expected": getattr(cls, "__name__", str(cls)), "got": type(payload).__name__},
    )


def route_start(target: Any, payload: Any = None) -> dict[str, Any]:
    params = _coerce_dataclass(BrowserTraceStartInput, payload)
    return asdict(start_trace(target, params))


def route_stop(target: Any, payload: Any = None) -> dict[str, Any]:
    _ = payload
    return asdict(stop_trace(target))


def route_export(target: Any, payload: Any) -> dict[str, Any]:
    params = _coerce_dataclass(BrowserTraceExportInput, payload)
    return asdict(export_trace(target, params))


ROUTES: dict[str, dict[str, Any]] = {
    "browser.trace.start": {
        "handler": route_start,
        "input": BrowserTraceStartInput,
        "output": BrowserTraceStartOutput,
        "input_schema": input_schemas()["start"],
        "output_schema": output_schemas()["start"],
    },
    "browser.trace.stop": {
        "handler": route_stop,
        "input": BrowserTraceStopInput,
        "output": BrowserTraceStopOutput,
        "input_schema": input_schemas()["stop"],
        "output_schema": output_schemas()["stop"],
    },
    "browser.trace.export": {
        "handler": route_export,
        "input": BrowserTraceExportInput,
        "output": BrowserTraceExportOutput,
        "input_schema": input_schemas()["export"],
        "output_schema": output_schemas()["export"],
    },
}

# Alias names used by some discovery systems.
ACTIONS = ROUTES
