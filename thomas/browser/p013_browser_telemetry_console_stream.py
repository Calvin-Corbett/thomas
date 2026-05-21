from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# -----------------------------
# Public contracts
# -----------------------------


@dataclass(frozen=True, slots=True)
class BrowserConsoleLocation:
    """Best-effort source location for a console message."""

    url: str | None = None
    line: int | None = None
    column: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "line": self.line, "column": self.column}


@dataclass(frozen=True, slots=True)
class BrowserConsoleEvent:
    """A single console message event captured from a browser page."""

    timestamp_ms: int
    level: str
    text: str
    location: BrowserConsoleLocation | None = None
    args: list[Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "timestamp_ms": self.timestamp_ms,
            "level": self.level,
            "text": self.text,
        }
        if self.location is not None:
            data["location"] = self.location.to_dict()
        if self.args is not None:
            data["args"] = self.args
        return data


@dataclass(frozen=True, slots=True)
class BrowserConsoleStreamInput:
    """Input contract for streaming console telemetry.

    Notes:
    - This attaches to ALL existing pages in the connected browser contexts.
    - It also attaches to newly created pages during the capture window.
    """

    # How to reach the existing live browser.
    cdp_url: str | None = None

    # How long to listen before returning.
    duration_seconds: float = 5.0

    # Safety cap.
    max_events: int = 250

    # Poll cadence while waiting (Playwright needs "wait_for_timeout" to pump events).
    poll_interval_seconds: float = 0.1

    # Optional filter: only include these console "levels" (Playwright ConsoleMessage.type).
    levels: Sequence[str] | None = None

    # Optional details.
    include_location: bool = False
    include_args: bool = False


@dataclass(frozen=True, slots=True)
class BrowserConsoleStreamOutput:
    """Output contract for console telemetry stream snapshot."""

    events: list[BrowserConsoleEvent] = field(default_factory=list)
    truncated: bool = False
    duration_seconds: float = 0.0
    cdp_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "truncated": self.truncated,
            "duration_seconds": self.duration_seconds,
            "cdp_url": self.cdp_url,
        }


def input_json_schema() -> dict[str, Any]:
    """Machine-readable schema for BrowserConsoleStreamInput."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "BrowserConsoleStreamInput",
        "type": "object",
        "properties": {
            "cdp_url": {"type": ["string", "null"]},
            "duration_seconds": {"type": "number", "default": 5.0},
            "max_events": {"type": "integer", "default": 250},
            "poll_interval_seconds": {"type": "number", "default": 0.1},
            "levels": {"type": ["array", "string", "null"]},
            "include_location": {"type": "boolean", "default": False},
            "include_args": {"type": "boolean", "default": False},
        },
    }


def output_json_schema() -> dict[str, Any]:
    """Machine-readable schema for BrowserConsoleStreamOutput."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "BrowserConsoleStreamOutput",
        "type": "object",
        "required": ["events", "truncated", "duration_seconds", "cdp_url"],
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["timestamp_ms", "level", "text"],
                    "properties": {
                        "timestamp_ms": {"type": "integer"},
                        "level": {"type": "string"},
                        "text": {"type": "string"},
                        "location": {
                            "type": "object",
                            "required": ["url", "line", "column"],
                            "properties": {
                                "url": {"type": ["string", "null"]},
                                "line": {"type": ["integer", "null"]},
                                "column": {"type": ["integer", "null"]},
                            },
                        },
                        "args": {"type": ["array", "null"]},
                    },
                },
            },
            "truncated": {"type": "boolean"},
            "duration_seconds": {"type": "number"},
            "cdp_url": {"type": ["string", "null"]},
        },
    }


INPUT_JSON_SCHEMA = input_json_schema()
OUTPUT_JSON_SCHEMA = output_json_schema()

# -----------------------------
# Deterministic error types
# -----------------------------


class BrowserTelemetryError(Exception):
    """Base class for deterministic browser telemetry failures."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class BrowserTelemetryInputError(BrowserTelemetryError):
    """Invalid user input (deterministic)."""


class BrowserTelemetryConfigError(BrowserTelemetryError):
    """Missing/invalid configuration (deterministic)."""


class BrowserTelemetryExternalError(BrowserTelemetryError):
    """External failure (browser unreachable, protocol error, etc.)."""


# -----------------------------
# Core behavior
# -----------------------------

_ENV_CANDIDATES: tuple[str, ...] = (
    "THOMAS_BROWSER_CDP_URL",
    "THOMAS_BROWSER_WS_ENDPOINT",
    "THOMAS_LIVE_BROWSER_CDP_URL",
    "THOMAS_LIVE_BROWSER_WS_ENDPOINT",
    "BROWSER_CDP_URL",
    "BROWSER_WS_ENDPOINT",
)


def _candidate_config_paths() -> list[Path]:
    home = Path.home()
    xdg = os.getenv("XDG_CONFIG_HOME")
    paths: list[Path] = []
    if xdg:
        paths.append(Path(xdg) / "thomas" / "browser.json")
        paths.append(Path(xdg) / "thomas" / "browser_telemetry.json")
    paths.append(home / ".config" / "thomas" / "browser.json")
    paths.append(home / ".config" / "thomas" / "browser_telemetry.json")
    paths.append(home / ".thomas" / "browser.json")
    return paths


def _discover_cdp_url(explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()

    for key in _ENV_CANDIDATES:
        val = os.getenv(key)
        if val and val.strip():
            return val.strip()

    # Try to discover via Thomas' existing config helpers if present.
    for mod_name in ("thomas.tools.browser", "thomas.cli.live_browser"):
        module = _safe_import(mod_name)
        if module is None:
            continue

        # Common constant names
        for attr in ("CDP_URL", "WS_ENDPOINT", "DEFAULT_CDP_URL", "DEFAULT_WS_ENDPOINT"):
            val = getattr(module, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()

        # Common helper function names
        for fn_name in (
            "get_cdp_url",
            "get_ws_endpoint",
            "get_browser_endpoint",
            "default_cdp_url",
            "default_ws_endpoint",
            "load_browser_config",
            "load_config",
        ):
            fn = getattr(module, fn_name, None)
            if not callable(fn):
                continue
            try:
                candidate = fn()
            except (RuntimeError, TypeError, AttributeError):
                continue

            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

            if isinstance(candidate, Mapping):
                for k in ("cdp_url", "cdpUrl", "ws_endpoint", "wsEndpoint", "endpoint", "ws_url", "url"):
                    v = candidate.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()

            for k in ("cdp_url", "cdpUrl", "ws_endpoint", "wsEndpoint", "endpoint", "ws_url", "url"):
                v = getattr(candidate, k, None)
                if isinstance(v, str) and v.strip():
                    return v.strip()

    # Conventional local config files as a last resort.
    for cfg_path in _candidate_config_paths():
        try:
            text = cfg_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, Mapping):
            for k in ("cdp_url", "cdpUrl", "ws_endpoint", "wsEndpoint", "endpoint", "ws_url", "url"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()

    raise BrowserTelemetryConfigError(
        code="browser_endpoint_missing",
        message=("No live browser endpoint configured. Provide --cdp-url or set THOMAS_BROWSER_CDP_URL."),
        details={"env_candidates": list(_ENV_CANDIDATES)},
    )


def _safe_import(module_name: str):
    try:
        return __import__(module_name, fromlist=["*"])
    except (ImportError, ModuleNotFoundError):
        return None


@contextlib.contextmanager
def _connect_over_cdp(cdp_url: str):
    """Connect to a running browser via CDP.

    Strategy:
    1) Try to delegate to Thomas-native helpers (if present).
    2) Fall back to Playwright's `chromium.connect_over_cdp`.
    """
    # 1) Thomas-native connection helpers, best-effort.
    for mod_name in ("thomas.tools.browser", "thomas.cli.live_browser"):
        module = _safe_import(mod_name)
        if module is None:
            continue

        for fn_name in (
            "connect_over_cdp",
            "connect_browser_over_cdp",
            "connect_live_browser",
            "connect_live_browser_over_cdp",
            "connect_cdp",
            "connect",
            "open_browser",
            "get_live_browser",
            "live_browser",
            "get_browser",
        ):
            fn = getattr(module, fn_name, None)
            if not callable(fn):
                continue

            for call in (
                lambda: fn(cdp_url),
                lambda: fn(endpoint=cdp_url),
                lambda: fn(ws_endpoint=cdp_url),
                lambda: fn(cdp_url=cdp_url),
            ):
                try:
                    res = call()
                except TypeError:
                    continue
                except (RuntimeError, AttributeError, ConnectionError):
                    # Don't fail hard on an unknown helper; keep searching.
                    continue

                # Context manager?
                if hasattr(res, "__enter__") and hasattr(res, "__exit__"):
                    with res as browser:
                        yield browser
                    return

                # Tuple? (browser, page) etc.
                if isinstance(res, tuple) and res:
                    browser = res[0]
                    if _looks_like_browser(browser):
                        try:
                            yield browser
                        finally:
                            _safe_close(browser)
                        return

                # Direct browser object?
                if _looks_like_browser(res):
                    try:
                        yield res
                    finally:
                        _safe_close(res)
                    return

    # 2) Playwright fallback.
    try:
        from playwright.sync_api import Error as PlaywrightError  # type: ignore
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise BrowserTelemetryExternalError(
            code="playwright_unavailable",
            message="Playwright is required for CDP connections but is not available.",
            details={"error": str(exc)},
        ) from exc

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(cdp_url)
            try:
                yield browser
            finally:
                with contextlib.suppress(Exception):
                    browser.close()
    except PlaywrightError as exc:
        raise BrowserTelemetryExternalError(
            code="browser_connection_failed",
            message="Failed to connect to the live browser endpoint.",
            details={"cdp_url": cdp_url, "error": str(exc)},
        ) from exc
    except Exception as exc:
        raise BrowserTelemetryExternalError(
            code="browser_connection_failed",
            message="Failed to connect to the live browser endpoint.",
            details={"cdp_url": cdp_url, "error": str(exc)},
        ) from exc


def _looks_like_browser(obj: Any) -> bool:
    return obj is not None and hasattr(obj, "contexts")


def _safe_close(browser: Any) -> None:
    with contextlib.suppress(Exception):
        close = getattr(browser, "close", None)
        if callable(close):
            close()


def stream_console(
    request: BrowserConsoleStreamInput,
    *,
    on_event: Callable[[BrowserConsoleEvent], None] | None = None,
) -> BrowserConsoleStreamOutput:
    """Stream console messages for a bounded duration and return the captured events.

    Deterministic errors:
    - BrowserTelemetryInputError
    - BrowserTelemetryConfigError
    - BrowserTelemetryExternalError
    """
    _validate_input(request)
    cdp_url = _discover_cdp_url(request.cdp_url)

    levels = None
    if request.levels is not None:
        levels = {str(l).strip().lower() for l in request.levels if str(l).strip()}

    events: list[BrowserConsoleEvent] = []
    truncated = False

    start_mono = time.monotonic()
    end_mono = start_mono + float(request.duration_seconds)

    with _connect_over_cdp(cdp_url) as browser:
        pages = _all_pages(browser)
        if not pages:
            raise BrowserTelemetryExternalError(
                code="no_pages",
                message="Connected to browser but found no pages to observe.",
                details={"cdp_url": cdp_url},
            )

        anchor_page = pages[0]

        def handle_console(msg: Any) -> None:
            nonlocal truncated

            if len(events) >= request.max_events:
                truncated = True
                return

            ev = _convert_console_message(
                msg,
                include_location=request.include_location,
                include_args=request.include_args,
            )

            if levels is not None and ev.level.lower() not in levels:
                return

            events.append(ev)
            if on_event is not None:
                try:
                    on_event(ev)
                except (RuntimeError, TypeError):
                    # Streaming callbacks should never crash capture.
                    pass

        # Attach to existing pages and new pages created during capture.
        for ctx in getattr(browser, "contexts", []) or []:
            with contextlib.suppress(Exception):
                ctx.on(
                    "page",
                    lambda page: page.on("console", handle_console),
                )

        for page in pages:
            with contextlib.suppress(Exception):
                page.on("console", handle_console)

        poll_ms = max(1, int(float(request.poll_interval_seconds) * 1000))
        while time.monotonic() < end_mono and len(events) < request.max_events:
            if not _pump_playwright(anchor_page, poll_ms):
                time.sleep(poll_ms / 1000.0)

    duration = max(0.0, time.monotonic() - start_mono)
    return BrowserConsoleStreamOutput(
        events=events,
        truncated=truncated,
        duration_seconds=duration,
        cdp_url=cdp_url,
    )


def _pump_playwright(anchor_page: Any, poll_ms: int) -> bool:
    """Best-effort to allow Playwright to process incoming events."""
    try:
        anchor_page.wait_for_timeout(poll_ms)
        return True
    except (RuntimeError, AttributeError, TimeoutError):
        return False


def _validate_input(request: BrowserConsoleStreamInput) -> None:
    errors: list[str] = []

    if request.duration_seconds <= 0:
        errors.append("duration_seconds must be > 0")
    if request.max_events <= 0:
        errors.append("max_events must be > 0")
    if request.poll_interval_seconds <= 0:
        errors.append("poll_interval_seconds must be > 0")

    if request.levels is not None:
        if not isinstance(request.levels, Sequence):
            errors.append("levels must be a sequence of strings")
        else:
            for level in request.levels:
                if not isinstance(level, str):
                    errors.append("levels must be a sequence of strings")
                    break

    if errors:
        raise BrowserTelemetryInputError(code="invalid_input", message="; ".join(errors))


def _all_pages(browser: Any) -> list[Any]:
    pages: list[Any] = []
    for ctx in getattr(browser, "contexts", []) or []:
        pages.extend(list(getattr(ctx, "pages", []) or []))
    return pages


def _convert_console_message(msg: Any, *, include_location: bool, include_args: bool) -> BrowserConsoleEvent:
    # Playwright ConsoleMessage.type is a string, e.g. "log", "error", "warning".
    level = _call_or_attr(msg, "type")
    level = str(level or "log")

    text = _call_or_attr(msg, "text")
    text = str(text or "")

    timestamp_ms = int(time.time() * 1000)

    location_obj: BrowserConsoleLocation | None = None
    if include_location:
        loc = _call_or_attr(msg, "location")
        if isinstance(loc, Mapping):
            location_obj = BrowserConsoleLocation(
                url=_safe_str(loc.get("url")),
                line=_safe_int(loc.get("lineNumber") or loc.get("line")),
                column=_safe_int(loc.get("columnNumber") or loc.get("column")),
            )
        else:
            location_obj = BrowserConsoleLocation(
                url=_safe_str(getattr(loc, "url", None)),
                line=_safe_int(getattr(loc, "lineNumber", None) or getattr(loc, "line", None)),
                column=_safe_int(getattr(loc, "columnNumber", None) or getattr(loc, "column", None)),
            )

        if location_obj and not (location_obj.url or location_obj.line or location_obj.column):
            location_obj = None

    args: list[Any] | None = None
    if include_args:
        raw_args = _call_or_attr(msg, "args")
        args = []
        for a in list(raw_args or []):
            args.append(_best_effort_handle_to_json(a))

    return BrowserConsoleEvent(
        timestamp_ms=timestamp_ms,
        level=level,
        text=text,
        location=location_obj,
        args=args,
    )


def _best_effort_handle_to_json(handle: Any) -> Any:
    # If we already have a JSON-friendly primitive, keep it as-is.
    if handle is None or isinstance(handle, (str, int, float, bool)):
        return handle

    # Some wrappers may surface args as plain lists/dicts instead of JSHandles.
    if isinstance(handle, (list, tuple, dict)):
        try:
            json.dumps(handle)
            return handle
        except (TypeError, ValueError):
            pass

    # Playwright JSHandle supports json_value() in sync API.
    for fn_name in ("json_value", "jsonValue"):
        fn = getattr(handle, fn_name, None)
        if callable(fn):
            try:
                return fn()
            except (RuntimeError, TypeError):
                break

    # Fallback: use str() representation; it's stable enough for logs.
    try:
        return str(handle)
    except (TypeError, ValueError):
        return "<unserializable>"


def _call_or_attr(obj: Any, name: str) -> Any:
    val = getattr(obj, name, None)
    if callable(val):
        try:
            return val()
        except (RuntimeError, TypeError):
            return None
    return val


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_str(value: Any) -> str | None:
    try:
        if value is None:
            return None
        s = str(value)
        return s if s.strip() else None
    except (TypeError, ValueError):
        return None


# -----------------------------
# Dict-in / dict-out runner (nodes / automation)
# -----------------------------


def run(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Run using plain dict input and output."""
    if not isinstance(payload, Mapping):
        raise BrowserTelemetryInputError(code="invalid_input", message="payload must be a mapping")

    levels = payload.get("levels")
    if isinstance(levels, str):
        levels = [p.strip() for p in levels.split(",") if p.strip()]

    try:
        req = BrowserConsoleStreamInput(
            cdp_url=_safe_str(payload.get("cdp_url") or payload.get("cdpUrl") or payload.get("endpoint")),
            duration_seconds=float(payload.get("duration_seconds") or payload.get("duration") or 5.0),
            max_events=int(payload.get("max_events") or payload.get("maxEvents") or 250),
            poll_interval_seconds=float(payload.get("poll_interval_seconds") or payload.get("poll") or 0.1),
            levels=levels if levels is None else list(levels),
            include_location=bool(payload.get("include_location", payload.get("includeLocation", False))),
            include_args=bool(payload.get("include_args", payload.get("includeArgs", False))),
        )
    except BrowserTelemetryError:
        raise
    except Exception as exc:
        raise BrowserTelemetryInputError(code="invalid_input", message=str(exc)) from exc

    return stream_console(req).to_dict()
