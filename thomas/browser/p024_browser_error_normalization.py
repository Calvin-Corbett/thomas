"""Browser error normalization.

Browser automation fails in wonderfully diverse ways:

* bad input (unknown element reference, invalid selector, malformed payload)
* missing configuration / missing dependency (browser disabled, Playwright missing)
* external failures (networking, backend outages, relay not connected)
* genuine internal bugs

Those failures often show up as raw Exceptions, dict payloads, or strings.
This module normalizes them into a *stable* contract that is:

* safe to log (redacts common secrets)
* safe to serialize (JSON-friendly)
* predictable for automation (stable `code`, `category`, `retryable`)

Callers should treat this as a best-effort classifier: it never raises.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

BrowserErrorCategory = Literal["input", "config", "external", "internal"]


@dataclass(frozen=True)
class BrowserErrorNormalizationRequest:
    """Input contract for browser error normalization."""

    raw: Any
    operation: str | None = None
    profile: str | None = None
    target_url: str | None = None
    http_status: int | None = None


@dataclass(frozen=True)
class BrowserErrorNormalizationResult:
    """Output contract for browser error normalization."""

    code: str
    category: BrowserErrorCategory
    message: str
    retryable: bool

    # Sanitized raw error text.
    raw: str

    # Optional context (echoed back).
    operation: str | None = None
    profile: str | None = None
    target_url: str | None = None
    http_status: int | None = None

    # Extra structured info (stable keys; JSON-serializable values).
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        out: dict[str, Any] = {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "retryable": self.retryable,
            "raw": self.raw,
        }
        if self.operation is not None:
            out["operation"] = self.operation
        if self.profile is not None:
            out["profile"] = self.profile
        if self.target_url is not None:
            out["target_url"] = self.target_url
        if self.http_status is not None:
            out["http_status"] = self.http_status
        if self.details:
            out["details"] = self.details
        return out


# A small JSON-schema-ish description for automation.
# (Kept intentionally minimal and stable; callers can hardcode keys if desired.)
BROWSER_ERROR_NORMALIZATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["code", "category", "message", "retryable", "raw"],
    "properties": {
        "code": {"type": "string"},
        "category": {"type": "string", "enum": ["input", "config", "external", "internal"]},
        "message": {"type": "string"},
        "retryable": {"type": "boolean"},
        "raw": {"type": "string"},
        "operation": {"type": "string"},
        "profile": {"type": "string"},
        "target_url": {"type": "string"},
        "http_status": {"type": "integer"},
        "details": {"type": "object"},
    },
}


def browser_error_normalization_schema() -> dict[str, Any]:
    """Return the normalization output schema."""

    # Defensive copy so callers can't mutate the module constant.
    return json.loads(json.dumps(BROWSER_ERROR_NORMALIZATION_SCHEMA))


_MAX_RAW_CHARS = 4000


def normalize_browser_error(
    request: BrowserErrorNormalizationRequest | Any,
    *,
    operation: str | None = None,
    profile: str | None = None,
    target_url: str | None = None,
    http_status: int | None = None,
) -> BrowserErrorNormalizationResult:
    """Normalize a browser error.

    Args:
        request: Either a :class:`BrowserErrorNormalizationRequest` or a raw error
            object (str/Exception/dict/list/etc).
        operation: Optional operation context (used only when ``request`` is raw).
        profile: Optional browser profile name (used only when ``request`` is raw).
        target_url: Optional URL that the operation was acting on.
        http_status: Optional upstream HTTP status code.

    Returns:
        A deterministic :class:`BrowserErrorNormalizationResult`.
    """

    if isinstance(request, BrowserErrorNormalizationRequest):
        req = request
    else:
        req = BrowserErrorNormalizationRequest(
            raw=request,
            operation=operation,
            profile=profile,
            target_url=target_url,
            http_status=http_status,
        )

    resolved_http_status = _extract_http_status(req.raw, req.http_status)
    error_type = _extract_error_type(req.raw)

    details: dict[str, Any] = {}
    if error_type:
        details["error_type"] = error_type

    if isinstance(req.raw, dict):
        details["raw_kind"] = "dict"
        keys = list(req.raw.keys())
        details["raw_keys"] = keys[:50]
        if len(keys) > 50:
            details["raw_keys_truncated"] = True
    elif isinstance(req.raw, (list, tuple)):
        details["raw_kind"] = "list"
        details["raw_len"] = len(req.raw)
    elif req.raw is None:
        details["raw_kind"] = "none"
    else:
        details["raw_kind"] = type(req.raw).__name__

    raw_text = _sanitize_error_text(_extract_error_text(req.raw)).strip()
    if len(raw_text) > _MAX_RAW_CHARS:
        details["raw_truncated"] = True
        raw_text = raw_text[:_MAX_RAW_CHARS] + "…"

    if not raw_text:
        return _result(
            code="browser_error_missing",
            category="input",
            message="No error details were provided.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "missing"},
        )

    lowered = raw_text.lower()

    # ------------------------------------------------------------------
    # High-signal input/validation issues
    # ------------------------------------------------------------------

    if _contains_any(lowered, ["jsondecodeerror", "invalid json", "json decode error"]):
        return _result(
            code="browser_payload_invalid",
            category="input",
            message="The browser payload was not valid JSON.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "payload_invalid"},
        )

    if _contains_any(
        lowered,
        [
            "invalid url",
            "no scheme supplied",
            "unknown url type",
            "malformed url",
        ],
    ):
        return _result(
            code="browser_url_invalid",
            category="input",
            message="The provided URL was not valid.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "url_invalid"},
        )

    if _contains_any(lowered, ["invalid selector", "selector syntax", "css selector"]):
        return _result(
            code="browser_selector_invalid",
            category="input",
            message="The selector used to locate an element was not valid.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "selector_invalid"},
        )

    if _contains_all(lowered, ["profile", "not found"]) or _contains_any(
        lowered,
        ["unknown profile", "no such profile"],
    ):
        return _result(
            code="browser_profile_not_found",
            category="input",
            message="The requested browser profile does not exist.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "profile_not_found"},
        )

    if _contains_any(
        lowered,
        [
            "unknown ref",
            "ref not found",
            "no node found",
            "element ref",
            "missing ref",
            "stale element reference",
        ],
    ):
        return _result(
            code="browser_ref_not_found",
            category="input",
            message="The target element reference could not be resolved.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "ref_not_found"},
        )

    # ------------------------------------------------------------------
    # Config / dependency gaps
    # ------------------------------------------------------------------

    if _contains_any(lowered, ["browser disabled", "disable browser"]) or (
        "browser" in lowered and "disabled" in lowered and "enable" in lowered
    ):
        return _result(
            code="browser_disabled",
            category="config",
            message="Browser automation is disabled in configuration.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "browser_disabled"},
        )

    if _contains_any(lowered, ["environment variable", "env var"]) and _contains_any(
        lowered,
        ["not set", "missing", "unset"],
    ):
        return _result(
            code="browser_env_missing",
            category="config",
            message="A required environment variable for browser automation is missing.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "env_missing"},
        )

    if ("config" in lowered or "configuration" in lowered) and _contains_any(
        lowered,
        ["not found", "missing", "no such file"],
    ):
        return _result(
            code="browser_config_missing",
            category="config",
            message="Browser configuration could not be loaded.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "config_missing"},
        )

    if resolved_http_status == 501:
        return _result(
            code="browser_dependency_missing",
            category="config",
            message="Browser automation requires an additional dependency that is not available.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "dependency_missing", "dependency": "unknown"},
        )

    if _contains_any(lowered, ["playwright"]) and _contains_any(
        lowered,
        ["not available", "not installed", "missing", "requires playwright"],
    ):
        return _result(
            code="browser_dependency_missing",
            category="config",
            message="Browser automation requires an additional dependency that is not available.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "dependency_missing", "dependency": "playwright"},
        )

    if _contains_any(lowered, ["executable doesn't exist", "file not found", "errno 2"]) and _contains_any(
        lowered,
        ["chrome", "chromium", "msedge", "playwright"],
    ):
        return _result(
            code="browser_executable_missing",
            category="config",
            message="The browser executable required for automation could not be found.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "executable_missing"},
        )

    # ------------------------------------------------------------------
    # External failures (network/backend)
    # ------------------------------------------------------------------

    if _contains_any(
        lowered,
        [
            "relay is running, but no tab is connected",
            "no tab is connected",
            "no tab connected",
            "not attached to any tab",
        ],
    ):
        return _result(
            code="browser_relay_not_connected",
            category="external",
            message="The browser relay is running but is not attached to a tab.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "relay_not_connected"},
        )

    if _contains_any(lowered, ["page crashed", "target closed", "browser has disconnected"]):
        return _result(
            code="browser_target_closed",
            category="external",
            message="The browser target was closed or crashed during the operation.",
            retryable=True,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "target_closed"},
        )

    if _contains_any(lowered, ["failed to start", "failed launching", "failed to launch"]) and _contains_any(
        lowered,
        ["cdp", "devtools", "remote debugging"],
    ):
        return _result(
            code="browser_launch_failed",
            category="external",
            message="The browser process failed to start or expose a debugging endpoint.",
            retryable=True,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "launch_failed"},
        )

    if _contains_any(
        lowered,
        [
            "can't reach",
            "cannot reach",
            "could not reach",
            "connection refused",
            "econnrefused",
            "connectex",
            "connection error",
        ],
    ) and _contains_any(lowered, ["browser", "cdp", "devtools", "control"]):
        return _result(
            code="browser_control_unreachable",
            category="external",
            message="The browser control endpoint is not reachable.",
            retryable=True,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "control_unreachable"},
        )

    if _contains_any(lowered, ["err_name_not_resolved", "name not resolved", "dns"]):
        return _result(
            code="browser_dns_error",
            category="external",
            message="DNS resolution failed while loading a page.",
            retryable=True,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "dns_error"},
        )

    if _contains_any(lowered, ["ssl", "certificate verify failed", "tls"]):
        return _result(
            code="browser_ssl_error",
            category="external",
            message="A TLS/SSL error occurred while communicating with the browser or loading a page.",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "ssl_error"},
        )

    if resolved_http_status in {401, 403} or _contains_any(lowered, ["unauthorized", "forbidden"]):
        return _result(
            code="browser_auth_failed",
            category="external",
            message="The browser backend rejected the request (authorization failed).",
            retryable=False,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "auth_failed"},
        )

    if resolved_http_status == 429 or _contains_any(lowered, ["rate limit", "too many requests"]):
        return _result(
            code="browser_rate_limited",
            category="external",
            message="The browser backend rate-limited the request.",
            retryable=True,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "rate_limited"},
        )

    if _contains_any(lowered, ["timed out", "timeout", "time out"]):
        return _result(
            code="browser_timeout",
            category="external",
            message="The browser operation timed out.",
            retryable=True,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "timeout"},
        )

    # ------------------------------------------------------------------
    # HTTP status mapping (fallback when no text rule matches)
    # ------------------------------------------------------------------

    mapped = _map_http_status(resolved_http_status)
    if mapped is not None:
        code, category, message, retryable = mapped
        return _result(
            code=code,
            category=category,
            message=message,
            retryable=retryable,
            raw=raw_text,
            req=req,
            http_status=resolved_http_status,
            details={**details, "rule": "http_status"},
        )

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    return _result(
        code="browser_unknown_error",
        category="internal",
        message="Unclassified browser failure.",
        retryable=False,
        raw=raw_text,
        req=req,
        http_status=resolved_http_status,
        details={**details, "rule": "unknown"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    *,
    code: str,
    category: BrowserErrorCategory,
    message: str,
    retryable: bool,
    raw: str,
    req: BrowserErrorNormalizationRequest,
    http_status: int | None,
    details: dict[str, Any],
) -> BrowserErrorNormalizationResult:
    return BrowserErrorNormalizationResult(
        code=code,
        category=category,
        message=message,
        retryable=retryable,
        raw=raw,
        operation=req.operation,
        profile=req.profile,
        target_url=req.target_url,
        http_status=http_status,
        details=details,
    )


def _contains_any(haystack: str, needles: Iterable[str]) -> bool:
    return any(n in haystack for n in needles)


def _contains_all(haystack: str, needles: Iterable[str]) -> bool:
    return all(n in haystack for n in needles)


_HTTP_STATUS_IN_TEXT_RE = re.compile(
    r"\b(?:http\s*)?(?:status|code)\s*[:=]?\s*(\d{3})\b",
    flags=re.IGNORECASE,
)


def _extract_http_status(raw: Any, explicit: int | None) -> int | None:
    if isinstance(explicit, int):
        return explicit

    # Exception objects sometimes carry an attached response.
    if isinstance(raw, BaseException):
        for attr in ("status_code", "status", "code"):
            v = getattr(raw, attr, None)
            if isinstance(v, int):
                return v
        resp = getattr(raw, "response", None)
        if resp is not None:
            for attr in ("status_code", "status", "code"):
                v = getattr(resp, attr, None)
                if isinstance(v, int):
                    return v

    if isinstance(raw, dict):
        for key in ("status", "status_code", "http_status", "code"):
            val = raw.get(key)
            if isinstance(val, int):
                return val
            if isinstance(val, str) and val.isdigit():
                try:
                    return int(val)
                except ValueError:
                    pass

    # As a last resort, pull from the textual message.
    text = _extract_error_text(raw)
    m = _HTTP_STATUS_IN_TEXT_RE.search(text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None

    return None


def _extract_error_type(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, BaseException):
        return raw.__class__.__name__
    if isinstance(raw, dict):
        for key in ("type", "error_type", "name", "kind", "exception"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _extract_error_text(raw: Any, *, _depth: int = 0) -> str:
    # Depth guard for recursive structures.
    if _depth > 4:
        return ""

    if raw is None:
        return ""

    if isinstance(raw, str):
        return raw

    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8", errors="replace")
        except (AttributeError, UnicodeDecodeError):
            return "<bytes>"

    if isinstance(raw, BaseException):
        text = str(raw).strip()
        return text or raw.__class__.__name__

    if isinstance(raw, dict):
        # Try common message keys first.
        for key in ("error", "message", "detail", "details", "reason", "cause", "errors"):
            if key in raw:
                text = _extract_error_text(raw.get(key), _depth=_depth + 1)
                if text:
                    return text

        # If it's a small dict of primitives, serialize it (stable order).
        try:
            if len(raw) <= 12 and all(isinstance(v, (str, int, float, bool, type(None))) for v in raw.values()):
                return json.dumps(raw, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            pass

        return "{...}" if raw else "{}"

    if isinstance(raw, (list, tuple)):
        parts = [_extract_error_text(v, _depth=_depth + 1) for v in raw]
        parts = [p for p in parts if p]
        return " | ".join(parts)

    # Avoid default object reprs that include memory addresses.
    try:
        text = str(raw)
    except (TypeError, ValueError):
        return raw.__class__.__name__

    if re.fullmatch(r"<\w+(?:\.\w+)* object at 0x[0-9a-fA-F]+>", text.strip()):
        return raw.__class__.__name__

    return text


_BASIC_AUTH_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^\s/@:]+):([^\s/@]+)@")
_QUERY_SECRET_RE = re.compile(
    r"([?&](?:token|access_token|api_key|apikey|key|secret|password|pwd|session|sessionid)=)[^&\s]+",
    flags=re.IGNORECASE,
)
_AUTHZ_RE = re.compile(
    r"(authorization\s*:\s*(?:bearer|token)\s+)[^\s\"']+",
    flags=re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\b(bearer\s+)[A-Za-z0-9._\-]+", flags=re.IGNORECASE)
_HEADER_API_KEY_RE = re.compile(r"((?:x-)?api[-_]?key\s*:\s*)[^\s,;]+", flags=re.IGNORECASE)
_COOKIE_RE = re.compile(r"(cookie\s*:\s*)[^\n\r]+", flags=re.IGNORECASE)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")


def _sanitize_error_text(text: str) -> str:
    # Basic auth in URLs: scheme://user:pass@host -> scheme://<redacted>:<redacted>@host
    text = _BASIC_AUTH_RE.sub(r"\1<redacted>:<redacted>@", text)

    # Common secret-ish query params.
    text = _QUERY_SECRET_RE.sub(r"\1<redacted>", text)

    # Authorization header tokens.
    text = _AUTHZ_RE.sub(r"\1<redacted>", text)

    # Loose "bearer XXX" patterns.
    text = _BEARER_RE.sub(r"\1<redacted>", text)

    # API key headers.
    text = _HEADER_API_KEY_RE.sub(r"\1<redacted>", text)

    # Cookie header contents.
    text = _COOKIE_RE.sub(r"\1<redacted>", text)

    # JWT-like tokens.
    text = _JWT_RE.sub("<redacted>", text)

    return text


def _map_http_status(status: int | None) -> tuple[str, BrowserErrorCategory, str, bool] | None:
    if not isinstance(status, int):
        return None

    if status < 400:
        return None

    if status == 400:
        return (
            "browser_http_bad_request",
            "input",
            "The browser backend rejected the request (bad request).",
            False,
        )

    if status in {401, 403}:
        return (
            "browser_auth_failed",
            "external",
            "The browser backend rejected the request (authorization failed).",
            False,
        )

    if status == 404:
        return (
            "browser_backend_not_found",
            "config",
            "The browser backend route was not found.",
            False,
        )

    if status == 408:
        return (
            "browser_timeout",
            "external",
            "The browser operation timed out.",
            True,
        )

    if status == 413:
        return (
            "browser_payload_too_large",
            "input",
            "The browser backend rejected the request (payload too large).",
            False,
        )

    if status in {422}:
        return (
            "browser_request_invalid",
            "input",
            "The browser backend rejected the request (validation failed).",
            False,
        )

    if status == 429:
        return (
            "browser_rate_limited",
            "external",
            "The browser backend rate-limited the request.",
            True,
        )

    if 500 <= status <= 599:
        # Gateway timeouts are effectively timeouts.
        if status == 504:
            return (
                "browser_timeout",
                "external",
                "The browser backend timed out.",
                True,
            )
        if status in {502, 503}:
            return (
                "browser_backend_unavailable",
                "external",
                "The browser backend is unavailable.",
                True,
            )
        return (
            "browser_backend_error",
            "external",
            "The browser backend encountered an error.",
            True,
        )

    # Generic fallback for other 4xx.
    if 400 <= status <= 499:
        return (
            "browser_http_client_error",
            "input",
            "The browser backend rejected the request (client error).",
            False,
        )

    return None


# Backwards/alternate naming (kept tiny; callers can pick whichever reads best).
normalize_browser_exception = normalize_browser_error


def normalize_browser_error_dict(
    request: BrowserErrorNormalizationRequest | Any,
    *,
    operation: str | None = None,
    profile: str | None = None,
    target_url: str | None = None,
    http_status: int | None = None,
) -> dict[str, Any]:
    """Convenience wrapper that returns a dict instead of a dataclass."""

    return normalize_browser_error(
        request,
        operation=operation,
        profile=profile,
        target_url=target_url,
        http_status=http_status,
    ).to_dict()
