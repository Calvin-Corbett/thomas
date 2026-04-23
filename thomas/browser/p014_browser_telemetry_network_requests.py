from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# -----------------------------
# Public contracts
# -----------------------------


@dataclass(frozen=True, slots=True)
class BrowserNetworkRequest:
    """A single network request (with best-effort response/failure info)."""

    id: str
    timestamp_ms: int
    method: str
    url: str
    resource_type: str | None = None

    request_headers: dict[str, str] | None = None
    post_data: str | None = None

    response_status: int | None = None
    response_headers: dict[str, str] | None = None

    failure_text: str | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp_ms": self.timestamp_ms,
            "method": self.method,
            "url": self.url,
            "resource_type": self.resource_type,
            "request_headers": self.request_headers,
            "post_data": self.post_data,
            "response_status": self.response_status,
            "response_headers": self.response_headers,
            "failure_text": self.failure_text,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True, slots=True)
class BrowserNetworkRequestsInput:
    """Input contract for capturing network request telemetry."""

    cdp_url: str | None = None
    duration_seconds: float = 5.0
    max_entries: int = 500
    poll_interval_seconds: float = 0.1

    include_headers: bool = False
    include_post_data: bool = False
    include_response_headers: bool = False


@dataclass(frozen=True, slots=True)
class BrowserNetworkRequestsOutput:
    """Output contract for network request capture."""

    requests: list[BrowserNetworkRequest] = field(default_factory=list)
    truncated: bool = False
    duration_seconds: float = 0.0
    cdp_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests": [r.to_dict() for r in self.requests],
            "truncated": self.truncated,
            "duration_seconds": self.duration_seconds,
            "cdp_url": self.cdp_url,
        }


def input_json_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "BrowserNetworkRequestsInput",
        "type": "object",
        "properties": {
            "cdp_url": {"type": ["string", "null"]},
            "duration_seconds": {"type": "number", "default": 5.0},
            "max_entries": {"type": "integer", "default": 500},
            "poll_interval_seconds": {"type": "number", "default": 0.1},
            "include_headers": {"type": "boolean", "default": False},
            "include_post_data": {"type": "boolean", "default": False},
            "include_response_headers": {"type": "boolean", "default": False},
        },
    }


def output_json_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "BrowserNetworkRequestsOutput",
        "type": "object",
        "required": ["requests", "truncated", "duration_seconds", "cdp_url"],
        "properties": {
            "requests": {"type": "array", "items": {"type": "object"}},
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

    for mod_name in ("thomas.tools.browser", "thomas.cli.live_browser"):
        module = _safe_import(mod_name)
        if module is None:
            continue

        for attr in ("CDP_URL", "WS_ENDPOINT", "DEFAULT_CDP_URL", "DEFAULT_WS_ENDPOINT"):
            val = getattr(module, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()

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
        message=("No live browser endpoint configured. " "Provide --cdp-url or set THOMAS_BROWSER_CDP_URL."),
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
    # 1) Thomas-native helpers (best-effort).
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
                    continue

                if hasattr(res, "__enter__") and hasattr(res, "__exit__"):
                    with res as browser:
                        yield browser
                    return

                if isinstance(res, tuple) and res:
                    browser = res[0]
                    if _looks_like_browser(browser):
                        try:
                            yield browser
                        finally:
                            _safe_close(browser)
                        return

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


def capture_network_requests(
    request: BrowserNetworkRequestsInput,
    *,
    on_event: Callable[[BrowserNetworkRequest], None] | None = None,
) -> BrowserNetworkRequestsOutput:
    """Capture network request telemetry for a bounded duration.

    Captures request start time on "request", then finalizes entries on:
    - "response"
    - "requestfailed"

    Pending requests at the end of the capture window are also emitted with:
    - response_status = None
    - failure_text = None
    - duration_ms based on capture end time

    Deterministic errors:
    - BrowserTelemetryInputError
    - BrowserTelemetryConfigError
    - BrowserTelemetryExternalError
    """
    _validate_input(request)

    cdp_url = _discover_cdp_url(request.cdp_url)
    start_mono = time.monotonic()
    end_mono = start_mono + float(request.duration_seconds)

    pending: dict[str, dict[str, Any]] = {}
    captured: list[BrowserNetworkRequest] = []
    truncated = False
    next_seq = 1

    with _connect_over_cdp(cdp_url) as browser:
        pages = _all_pages(browser)
        if not pages:
            raise BrowserTelemetryExternalError(
                code="no_pages",
                message="Connected to browser but found no pages to observe.",
                details={"cdp_url": cdp_url},
            )

        anchor_page = pages[0]

        def handle_request(req_obj: Any) -> None:
            nonlocal next_seq, truncated

            if len(captured) >= request.max_entries:
                truncated = True
                return

            key = _request_key(req_obj)
            if key in pending:
                # Duplicate key should be rare; avoid clobbering older entry.
                key = f"{key}:{next_seq}"

            now_ms = int(time.time() * 1000)
            method = _safe_str(_call_or_attr(req_obj, "method")) or "GET"
            url = _safe_str(_call_or_attr(req_obj, "url")) or ""
            resource_type = _safe_str(_call_or_attr(req_obj, "resource_type") or _call_or_attr(req_obj, "resourceType"))

            entry: dict[str, Any] = {
                "id": str(next_seq),
                "timestamp_ms": now_ms,
                "method": method,
                "url": url,
                "resource_type": resource_type,
                "request_headers": None,
                "post_data": None,
                "response_status": None,
                "response_headers": None,
                "failure_text": None,
                "start_mono": time.monotonic(),
            }
            next_seq += 1

            if request.include_headers:
                entry["request_headers"] = _safe_dict_str_str(_call_or_attr(req_obj, "headers")) or {}

            if request.include_post_data:
                post_data = _call_or_attr(req_obj, "post_data") or _call_or_attr(req_obj, "postData")
                entry["post_data"] = _safe_str(post_data)

            pending[key] = entry

        def handle_response(resp_obj: Any) -> None:
            req_obj = _call_or_attr(resp_obj, "request")
            key = _request_key(req_obj) if req_obj is not None else None
            if not key or key not in pending:
                # If we can't correlate, we still emit a minimal entry (best-effort).
                _emit_uncorrelated_response(resp_obj)
                return

            entry = pending[key]
            status = _call_or_attr(resp_obj, "status")
            try:
                entry["response_status"] = int(status) if status is not None else None
            except (ValueError, TypeError):
                entry["response_status"] = None

            if request.include_response_headers:
                entry["response_headers"] = _safe_dict_str_str(_call_or_attr(resp_obj, "headers")) or {}

            _finalize_entry(key, entry)

        def handle_failed(req_obj: Any) -> None:
            key = _request_key(req_obj)
            entry = pending.get(key)
            if entry is None:
                return

            failure = _call_or_attr(req_obj, "failure")
            if isinstance(failure, Mapping):
                entry["failure_text"] = _safe_str(failure.get("errorText"))
            else:
                entry["failure_text"] = _safe_str(getattr(failure, "errorText", None))

            _finalize_entry(key, entry)

        def _finalize_entry(key: str, entry: dict[str, Any]) -> None:
            nonlocal truncated
            if len(captured) >= request.max_entries:
                truncated = True
                pending.pop(key, None)
                return

            duration_ms = int((time.monotonic() - float(entry.get("start_mono", time.monotonic()))) * 1000)
            entry["duration_ms"] = duration_ms
            captured.append(_to_request(entry))
            pending.pop(key, None)

            if on_event is not None:
                try:
                    on_event(captured[-1])
                except (RuntimeError, TypeError):
                    pass

        def _emit_uncorrelated_response(resp_obj: Any) -> None:
            # Best-effort: a response without seeing the request event (rare but possible).
            nonlocal truncated, next_seq
            if len(captured) >= request.max_entries:
                truncated = True
                return

            req_obj = _call_or_attr(resp_obj, "request")
            now_ms = int(time.time() * 1000)
            method = _safe_str(_call_or_attr(req_obj, "method")) or "GET"
            url = _safe_str(_call_or_attr(req_obj, "url")) or ""
            resource_type = _safe_str(_call_or_attr(req_obj, "resource_type") or _call_or_attr(req_obj, "resourceType"))

            status = _call_or_attr(resp_obj, "status")
            try:
                status_i = int(status) if status is not None else None
            except (ValueError, TypeError):
                status_i = None

            resp_headers = None
            if request.include_response_headers:
                resp_headers = _safe_dict_str_str(_call_or_attr(resp_obj, "headers")) or {}

            captured.append(
                BrowserNetworkRequest(
                    id=str(next_seq),
                    timestamp_ms=now_ms,
                    method=method,
                    url=url,
                    resource_type=resource_type,
                    response_status=status_i,
                    response_headers=resp_headers,
                )
            )
            next_seq += 1

        for ctx in getattr(browser, "contexts", []) or []:
            with contextlib.suppress(Exception):
                ctx.on(
                    "page",
                    lambda page: _attach_page_listeners(page, handle_request, handle_response, handle_failed),
                )

        for page in pages:
            _attach_page_listeners(page, handle_request, handle_response, handle_failed)

        poll_ms = max(1, int(float(request.poll_interval_seconds) * 1000))
        while time.monotonic() < end_mono and len(captured) < request.max_entries:
            if not _pump_playwright(anchor_page, poll_ms):
                time.sleep(poll_ms / 1000.0)

    # Flush pending at end of capture.
    for key, entry in list(pending.items()):
        if len(captured) >= request.max_entries:
            truncated = True
            break
        duration_ms = int((time.monotonic() - float(entry.get("start_mono", time.monotonic()))) * 1000)
        entry["duration_ms"] = duration_ms
        captured.append(_to_request(entry))
        pending.pop(key, None)

    # Stable ordering: id is a monotonically increasing sequence.
    captured.sort(key=lambda r: int(r.id) if r.id.isdigit() else 10**12)

    duration = max(0.0, time.monotonic() - start_mono)
    return BrowserNetworkRequestsOutput(
        requests=captured,
        truncated=truncated,
        duration_seconds=duration,
        cdp_url=cdp_url,
    )


def _pump_playwright(anchor_page: Any, poll_ms: int) -> bool:
    try:
        anchor_page.wait_for_timeout(poll_ms)
        return True
    except (RuntimeError, AttributeError, TimeoutError):
        return False


def _validate_input(request: BrowserNetworkRequestsInput) -> None:
    errors: list[str] = []
    if request.duration_seconds <= 0:
        errors.append("duration_seconds must be > 0")
    if request.max_entries <= 0:
        errors.append("max_entries must be > 0")
    if request.poll_interval_seconds <= 0:
        errors.append("poll_interval_seconds must be > 0")
    if errors:
        raise BrowserTelemetryInputError(code="invalid_input", message="; ".join(errors))


def _all_pages(browser: Any) -> list[Any]:
    pages: list[Any] = []
    for ctx in getattr(browser, "contexts", []) or []:
        pages.extend(list(getattr(ctx, "pages", []) or []))
    return pages


def _attach_page_listeners(page: Any, on_req: Any, on_resp: Any, on_failed: Any) -> None:
    with contextlib.suppress(Exception):
        page.on("request", on_req)
    with contextlib.suppress(Exception):
        page.on("response", on_resp)
    with contextlib.suppress(Exception):
        page.on("requestfailed", on_failed)


def _request_key(req_obj: Any) -> str:
    """Best-effort stable request identifier.

    Why this exists:
    - In Playwright Python, wrapper objects can be recreated, so `id(obj)` is not reliable for correlation.
    - Most Playwright channel objects expose an internal guid; we use it if present.

    Fallback is `id(req_obj)`.
    """
    if req_obj is None:
        return ""

    # Common internal attribute on Playwright's channel objects.
    guid = getattr(req_obj, "_guid", None)
    if isinstance(guid, str) and guid:
        return guid

    impl = getattr(req_obj, "_impl_obj", None)
    guid2 = getattr(impl, "_guid", None) if impl is not None else None
    if isinstance(guid2, str) and guid2:
        return guid2

    # Some wrappers may store identifiers in initializer dicts.
    initializer = getattr(req_obj, "_initializer", None)
    if isinstance(initializer, Mapping):
        for k in ("requestId", "request_id", "id", "guid"):
            v = initializer.get(k)
            if isinstance(v, str) and v:
                return v

    return str(id(req_obj))


def _to_request(entry: Mapping[str, Any]) -> BrowserNetworkRequest:
    return BrowserNetworkRequest(
        id=str(entry.get("id", "")),
        timestamp_ms=int(entry.get("timestamp_ms", 0)),
        method=str(entry.get("method", "")),
        url=str(entry.get("url", "")),
        resource_type=_safe_str(entry.get("resource_type")),
        request_headers=entry.get("request_headers"),
        post_data=_safe_str(entry.get("post_data")),
        response_status=entry.get("response_status"),
        response_headers=entry.get("response_headers"),
        failure_text=_safe_str(entry.get("failure_text")),
        duration_ms=entry.get("duration_ms"),
    )


def _call_or_attr(obj: Any, name: str) -> Any:
    val = getattr(obj, name, None)
    if callable(val):
        try:
            return val()
        except (RuntimeError, TypeError):
            return None
    return val


def _safe_str(value: Any) -> str | None:
    try:
        if value is None:
            return None
        s = str(value)
        return s if s.strip() else None
    except (TypeError, ValueError):
        return None


def _safe_dict_str_str(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        out: dict[str, str] = {}
        for k, v in value.items():
            ks = _safe_str(k)
            vs = _safe_str(v)
            if ks is not None and vs is not None:
                out[ks] = vs
        return out
    return None


# -----------------------------
# Dict-in / dict-out runner (nodes / automation)
# -----------------------------


def run(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise BrowserTelemetryInputError(code="invalid_input", message="payload must be a mapping")

    try:
        req = BrowserNetworkRequestsInput(
            cdp_url=_safe_str(payload.get("cdp_url") or payload.get("cdpUrl") or payload.get("endpoint")),
            duration_seconds=float(payload.get("duration_seconds") or payload.get("duration") or 5.0),
            max_entries=int(payload.get("max_entries") or payload.get("maxEntries") or 500),
            poll_interval_seconds=float(payload.get("poll_interval_seconds") or payload.get("poll") or 0.1),
            include_headers=bool(payload.get("include_headers", payload.get("includeHeaders", False))),
            include_post_data=bool(payload.get("include_post_data", payload.get("includePostData", False))),
            include_response_headers=bool(
                payload.get("include_response_headers", payload.get("includeResponseHeaders", False))
            ),
        )
    except BrowserTelemetryError:
        raise
    except Exception as exc:
        raise BrowserTelemetryInputError(code="invalid_input", message=str(exc)) from exc

    return capture_network_requests(req).to_dict()
