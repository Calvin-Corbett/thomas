"""thomas.browser.p011_browser_artifact_dom_snapshot

P011 - Browser artifact DOM snapshot.

Thomas-native behavior for capturing the current browser DOM and writing it as an
artifact.

Design goals
- Strong-ish typed input/output contracts.
- Works with multiple possible "browser" objects (LiveBrowser wrapper, Playwright
  Page, etc.) by trying a few safe capture strategies.
- Deterministic error codes for invalid input, missing config, and external
  failures.

Capture strategies (in order)
1) Browser-provided method: dom_snapshot/get_dom_snapshot/capture_dom_snapshot
2) CDP DOMSnapshot.captureSnapshot (Chromium via Playwright)
3) HTML fallback: page.content() / document.documentElement.outerHTML

Notes
- This module does *not* rely on any legacy naming.
- This module is intentionally conservative about importing other Thomas modules
  (config is resolved best-effort).
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

ErrorCategory = Literal["invalid_input", "missing_config", "external_failure"]
CaptureMethod = Literal["browser_method", "cdp", "html"]


class BrowserDomSnapshotError(Exception):
    """Deterministic error for DOM snapshot capture & artifact writing."""

    code: str
    category: ErrorCategory
    message: str
    detail: str | None

    def __init__(
        self,
        *,
        code: str,
        category: ErrorCategory,
        message: str,
        detail: str | None = None,
    ) -> None:
        # Keep the exception message deterministic: no repr(OS errors), no traces.
        super().__init__(f"{code}: {message}")
        self.code = code
        self.category = category
        self.message = message
        self.detail = detail


@dataclass(frozen=True)
class BrowserArtifactDomSnapshotInput:
    """Input contract for capturing a DOM snapshot."""

    artifacts_dir: str | None = None
    output_path: str | None = None
    base_name: str | None = None
    prefer_cdp: bool = True
    timeout_ms: int = 5_000


@dataclass(frozen=True)
class BrowserArtifactDomSnapshotOutput:
    """Output contract for a successful capture."""

    artifact_path: str
    bytes_written: int
    content_type: str
    capture_method: CaptureMethod
    sha256: str


class _CdpDomSnapshot(TypedDict, total=False):
    documents: list[Any]
    strings: list[str]


def browser_artifact_dom_snapshot(
    browser: Any,
    request: BrowserArtifactDomSnapshotInput,
) -> BrowserArtifactDomSnapshotOutput:
    """Synchronous entrypoint.

    If the browser integration is async-only and there's already a running event
    loop, callers must use :func:`browser_artifact_dom_snapshot_async`.
    """

    if _looks_async(browser):
        # Avoid attempting to nest event loops in an unknown runtime.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(browser_artifact_dom_snapshot_async(browser, request))
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_ASYNC_REQUIRED",
            category="external_failure",
            message="Browser integration is async-only; use browser_artifact_dom_snapshot_async().",
        )

    return _browser_artifact_dom_snapshot_sync(browser, request)


async def browser_artifact_dom_snapshot_async(
    browser: Any,
    request: BrowserArtifactDomSnapshotInput,
) -> BrowserArtifactDomSnapshotOutput:
    """Async entrypoint."""

    _validate_request(request)
    artifacts_dir, output_path = _resolve_output_location(request)

    payload, content_type, capture_method = await _capture_payload_async(
        browser=browser,
        prefer_cdp=request.prefer_cdp,
        timeout_ms=request.timeout_ms,
    )

    artifact_path, bytes_written, sha256 = _write_artifact(
        artifacts_dir=artifacts_dir,
        output_path=output_path,
        base_name=request.base_name,
        payload=payload,
        content_type=content_type,
        capture_method=capture_method,
    )

    return BrowserArtifactDomSnapshotOutput(
        artifact_path=str(artifact_path),
        bytes_written=bytes_written,
        content_type=content_type,
        capture_method=capture_method,
        sha256=sha256,
    )


def output_to_json(output: BrowserArtifactDomSnapshotOutput) -> str:
    """Machine-readable JSON for automation."""

    return json.dumps(asdict(output), sort_keys=True, ensure_ascii=False)


# ------------------------- Internal helpers ---------------------------------


def _browser_artifact_dom_snapshot_sync(
    browser: Any,
    request: BrowserArtifactDomSnapshotInput,
) -> BrowserArtifactDomSnapshotOutput:
    _validate_request(request)
    artifacts_dir, output_path = _resolve_output_location(request)

    payload, content_type, capture_method = _capture_payload_sync(
        browser=browser,
        prefer_cdp=request.prefer_cdp,
        timeout_ms=request.timeout_ms,
    )

    artifact_path, bytes_written, sha256 = _write_artifact(
        artifacts_dir=artifacts_dir,
        output_path=output_path,
        base_name=request.base_name,
        payload=payload,
        content_type=content_type,
        capture_method=capture_method,
    )

    return BrowserArtifactDomSnapshotOutput(
        artifact_path=str(artifact_path),
        bytes_written=bytes_written,
        content_type=content_type,
        capture_method=capture_method,
        sha256=sha256,
    )


def _validate_request(request: BrowserArtifactDomSnapshotInput) -> None:
    if request.timeout_ms <= 0:
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT",
            category="invalid_input",
            message="timeout_ms must be a positive integer.",
        )

    if request.artifacts_dir is not None and str(request.artifacts_dir).strip() == "":
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT",
            category="invalid_input",
            message="artifacts_dir cannot be an empty string.",
        )

    if request.output_path is not None and str(request.output_path).strip() == "":
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT",
            category="invalid_input",
            message="output_path cannot be an empty string.",
        )

    if request.output_path is not None and request.artifacts_dir is not None:
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT",
            category="invalid_input",
            message="Provide either output_path or artifacts_dir, not both.",
        )


def _resolve_output_location(request: BrowserArtifactDomSnapshotInput) -> tuple[Path, Path | None]:
    """Return (artifacts_dir, output_path)."""

    if request.output_path is not None:
        out_path = _ensure_output_path(Path(request.output_path))
        artifacts_dir = _ensure_artifacts_dir(out_path.parent)
        return artifacts_dir, out_path

    artifacts_dir = _resolve_artifacts_dir(request.artifacts_dir)
    return artifacts_dir, None


def _resolve_artifacts_dir(explicit: str | None) -> Path:
    if explicit is not None:
        return _ensure_artifacts_dir(Path(explicit))

    env_dir = os.getenv("THOMAS_ARTIFACTS_DIR") or os.getenv("THOMAS_ARTIFACT_DIR")
    if env_dir:
        return _ensure_artifacts_dir(Path(env_dir))

    config_dir = _try_resolve_artifacts_dir_from_thomas_config()
    if config_dir is not None:
        return _ensure_artifacts_dir(Path(config_dir))

    raise BrowserDomSnapshotError(
        code="THOMAS_BROWSER_DOM_SNAPSHOT_MISSING_CONFIG",
        category="missing_config",
        message="No artifacts_dir provided and no default artifacts directory configured.",
    )


def _ensure_artifacts_dir(path: Path) -> Path:
    try:
        path = path.expanduser()
    except (ValueError, OSError, RuntimeError):
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT",
            category="invalid_input",
            message="artifacts_dir is not a valid path.",
        )

    if path.exists() and not path.is_dir():
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT",
            category="invalid_input",
            message="artifacts_dir must be a directory path.",
        )

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_EXTERNAL_FAILURE",
            category="external_failure",
            message="Failed to create artifacts directory.",
        )

    return path


def _ensure_output_path(path: Path) -> Path:
    try:
        path = path.expanduser()
    except (ValueError, OSError, RuntimeError):
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT",
            category="invalid_input",
            message="output_path is not a valid path.",
        )

    if path.exists() and path.is_dir():
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT",
            category="invalid_input",
            message="output_path must be a file path, not a directory.",
        )

    return path


def _try_resolve_artifacts_dir_from_thomas_config() -> str | None:
    """Best-effort integration hook into Thomas config."""

    candidate_modules = (
        "thomas.config",
        "thomas.settings",
        "thomas.runtime.config",
        "thomas.cli.main",
    )
    candidate_attrs = (
        "ARTIFACTS_DIR",
        "artifacts_dir",
        "DEFAULT_ARTIFACTS_DIR",
        "default_artifacts_dir",
    )
    candidate_fns = (
        "get_artifacts_dir",
        "get_default_artifacts_dir",
        "resolve_artifacts_dir",
    )

    for mod_name in candidate_modules:
        try:
            mod = importlib.import_module(mod_name)
        except (ImportError, ModuleNotFoundError):
            continue

        for attr in candidate_attrs:
            value = getattr(mod, attr, None)
            if isinstance(value, str) and value.strip():
                return value

        for fn_name in candidate_fns:
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                try:
                    value = fn()
                except (RuntimeError, TypeError, AttributeError):
                    continue
                if isinstance(value, str) and value.strip():
                    return value

    return None


def _looks_async(browser: Any) -> bool:
    try:
        page = getattr(browser, "page", None) or browser
        content = getattr(page, "content", None)
        return callable(content) and inspect.iscoroutinefunction(content)
    except (AttributeError, TypeError):
        return False


def _capture_payload_sync(
    *,
    browser: Any,
    prefer_cdp: bool,
    timeout_ms: int,
) -> tuple[bytes, str, CaptureMethod]:
    if browser is None:
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_MISSING_CONFIG",
            category="missing_config",
            message="No active browser instance available.",
        )

    # 1) Browser-provided method.
    method_payload = _try_browser_method_sync(browser, timeout_ms=timeout_ms)
    if method_payload is not None:
        return method_payload

    # 2) CDP snapshot.
    if prefer_cdp:
        try:
            cdp = _try_capture_via_cdp_sync(browser)
            if cdp is not None:
                payload = _encode_json_payload(cdp)
                return payload, "application/json", "cdp"
        except BrowserDomSnapshotError:
            raise
        except (RuntimeError, AttributeError, TimeoutError):
            # Deterministic fallthrough.
            pass

    # 3) HTML fallback.
    html = _try_capture_html_sync(browser)
    if html is not None:
        return html.encode("utf-8"), "text/html", "html"

    raise BrowserDomSnapshotError(
        code="THOMAS_BROWSER_DOM_SNAPSHOT_CAPTURE_FAILED",
        category="external_failure",
        message="Failed to capture DOM snapshot from the active browser.",
    )


async def _capture_payload_async(
    *,
    browser: Any,
    prefer_cdp: bool,
    timeout_ms: int,
) -> tuple[bytes, str, CaptureMethod]:
    if browser is None:
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_MISSING_CONFIG",
            category="missing_config",
            message="No active browser instance available.",
        )

    # 1) Browser-provided method.
    method_payload = await _try_browser_method_async(browser, timeout_ms=timeout_ms)
    if method_payload is not None:
        return method_payload

    # 2) CDP snapshot.
    if prefer_cdp:
        try:
            cdp = await _try_capture_via_cdp_async(browser)
            if cdp is not None:
                payload = _encode_json_payload(cdp)
                return payload, "application/json", "cdp"
        except BrowserDomSnapshotError:
            raise
        except (RuntimeError, AttributeError, TimeoutError, asyncio.TimeoutError):
            pass

    # 3) HTML fallback.
    html = await _try_capture_html_async(browser)
    if html is not None:
        return html.encode("utf-8"), "text/html", "html"

    raise BrowserDomSnapshotError(
        code="THOMAS_BROWSER_DOM_SNAPSHOT_CAPTURE_FAILED",
        category="external_failure",
        message="Failed to capture DOM snapshot from the active browser.",
    )


def _try_browser_method_sync(browser: Any, *, timeout_ms: int) -> tuple[bytes, str, CaptureMethod] | None:
    for method_name in ("dom_snapshot", "get_dom_snapshot", "capture_dom_snapshot"):
        method = getattr(browser, method_name, None)
        if not callable(method):
            continue

        try:
            result = method(timeout_ms=timeout_ms)  # type: ignore[misc]
        except TypeError:
            result = method()
        except (RuntimeError, AttributeError):
            result = None

        if result is None:
            continue

        payload, content_type = _normalize_result_to_payload(result)
        return payload, content_type, "browser_method"

    return None


async def _try_browser_method_async(browser: Any, *, timeout_ms: int) -> tuple[bytes, str, CaptureMethod] | None:
    for method_name in ("dom_snapshot", "get_dom_snapshot", "capture_dom_snapshot"):
        method = getattr(browser, method_name, None)
        if not callable(method):
            continue

        try:
            result = method(timeout_ms=timeout_ms)  # type: ignore[misc]
        except TypeError:
            result = method()
        except (RuntimeError, AttributeError):
            result = None

        if inspect.isawaitable(result):
            try:
                result = await cast(Any, result)
            except (RuntimeError, TimeoutError, asyncio.TimeoutError):
                result = None

        if result is None:
            continue

        payload, content_type = _normalize_result_to_payload(result)
        return payload, content_type, "browser_method"

    return None


def _normalize_result_to_payload(result: Any) -> tuple[bytes, str]:
    """Convert an arbitrary result object into (payload_bytes, content_type)."""

    # dict/list -> JSON
    if isinstance(result, (dict, list)):
        return _encode_json_payload(result), "application/json"

    # str -> detect html-ish, else JSON-string
    if isinstance(result, str):
        s = result.lstrip()
        if _looks_like_html(s):
            return result.encode("utf-8"), "text/html"
        # If it parses as JSON, store it pretty.
        try:
            parsed = json.loads(result)
        except (ValueError, json.JSONDecodeError):
            parsed = result
        return _encode_json_payload(parsed), "application/json"

    # bytes-like -> detect html-ish, else error (avoid writing unknown binary)
    if isinstance(result, (bytes, bytearray)):
        b = bytes(result)
        if _looks_like_html_bytes(b):
            return b, "text/html"
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_EXTERNAL_FAILURE",
            category="external_failure",
            message="Browser snapshot returned unsupported binary payload.",
        )

    # Anything else -> JSON encode via repr-ish, but stable.
    return _encode_json_payload(result), "application/json"


def _looks_like_html(s: str) -> bool:
    head = s[:256].lower()
    if not head.startswith("<"):
        return False
    return "<html" in head or "<!doctype" in head or "</" in head


def _looks_like_html_bytes(b: bytes) -> bool:
    try:
        s = b[:256].decode("utf-8", errors="ignore").lower()
    except UnicodeDecodeError:
        return False
    return _looks_like_html(s)


def _encode_json_payload(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")


def _try_capture_via_cdp_sync(browser: Any) -> _CdpDomSnapshot | None:
    page = getattr(browser, "page", None) or browser
    context = getattr(page, "context", None)
    if context is None:
        return None

    new_cdp_session = getattr(context, "new_cdp_session", None)
    if not callable(new_cdp_session):
        return None

    try:
        cdp = new_cdp_session(page)
    except TypeError:
        cdp = new_cdp_session()

    send = getattr(cdp, "send", None)
    if not callable(send):
        return None

    result = send("DOMSnapshot.captureSnapshot", {"computedStyles": []})
    if not isinstance(result, dict):
        return None

    return cast(_CdpDomSnapshot, result)


async def _try_capture_via_cdp_async(browser: Any) -> _CdpDomSnapshot | None:
    page = getattr(browser, "page", None) or browser
    context = getattr(page, "context", None)
    if context is None:
        return None

    new_cdp_session = getattr(context, "new_cdp_session", None)
    if not callable(new_cdp_session):
        return None

    try:
        cdp = new_cdp_session(page)
    except TypeError:
        cdp = new_cdp_session()

    if inspect.isawaitable(cdp):
        cdp = await cast(Any, cdp)

    send = getattr(cdp, "send", None)
    if not callable(send):
        return None

    result = send("DOMSnapshot.captureSnapshot", {"computedStyles": []})
    if inspect.isawaitable(result):
        result = await cast(Any, result)

    if not isinstance(result, dict):
        return None

    return cast(_CdpDomSnapshot, result)


def _try_capture_html_sync(browser: Any) -> str | None:
    page = getattr(browser, "page", None) or browser

    content = getattr(page, "content", None)
    if callable(content):
        try:
            html = content()
        except (RuntimeError, TimeoutError):
            html = None
        if isinstance(html, str):
            return html

    evaluate = getattr(page, "evaluate", None) or getattr(page, "eval", None)
    if callable(evaluate):
        try:
            html = evaluate("document.documentElement.outerHTML")
        except (RuntimeError, TimeoutError):
            html = None
        if isinstance(html, str):
            return html

    return None


async def _try_capture_html_async(browser: Any) -> str | None:
    page = getattr(browser, "page", None) or browser

    content = getattr(page, "content", None)
    if callable(content):
        try:
            html = content()
            if inspect.isawaitable(html):
                html = await cast(Any, html)
        except (RuntimeError, TimeoutError, asyncio.TimeoutError):
            html = None
        if isinstance(html, str):
            return html

    evaluate = getattr(page, "evaluate", None) or getattr(page, "eval", None)
    if callable(evaluate):
        try:
            html = evaluate("document.documentElement.outerHTML")
            if inspect.isawaitable(html):
                html = await cast(Any, html)
        except (RuntimeError, TimeoutError, asyncio.TimeoutError):
            html = None
        if isinstance(html, str):
            return html

    return None


_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _sanitize_base_name(value: str) -> str:
    cleaned = _SANITIZE_RE.sub("-", value.strip()).strip("-")
    return cleaned or "dom-snapshot"


def _write_artifact(
    *,
    artifacts_dir: Path,
    output_path: Path | None,
    base_name: str | None,
    payload: bytes,
    content_type: str,
    capture_method: CaptureMethod,
) -> tuple[Path, int, str]:
    ext = ".json" if content_type == "application/json" else ".html"

    if output_path is not None:
        out_path = output_path
        if out_path.suffix == "":
            out_path = out_path.with_suffix(ext)
        return _safe_write(out_path, payload)

    safe_base = _sanitize_base_name(base_name) if base_name else "dom-snapshot"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = artifacts_dir / f"{safe_base}-{ts}-{capture_method}{ext}"
    return _safe_write(out_path, payload)


def _safe_write(path: Path, payload: bytes) -> tuple[Path, int, str]:
    sha256 = hashlib.sha256(payload).hexdigest()
    try:
        path.write_bytes(payload)
    except OSError:
        raise BrowserDomSnapshotError(
            code="THOMAS_BROWSER_DOM_SNAPSHOT_EXTERNAL_FAILURE",
            category="external_failure",
            message="Failed to write DOM snapshot artifact.",
        )
    return path, len(payload), sha256
