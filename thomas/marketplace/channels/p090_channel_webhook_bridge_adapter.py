"""
Webhook bridge channel adapter.

Thomas-native behavior:
- Outbound adapter that delivers a JSON payload to an arbitrary HTTP webhook endpoint.
- Useful as a bridge into systems that accept incoming webhooks (Slack/Discord/Teams/custom).

Key properties:
- Dependency-light: standard library only (urllib); no third-party HTTP client required.
- Deterministic failures: raises WebhookBridgeAdapterError with stable error codes.
- Automation-friendly: provides a small JSON Schema for a default payload shape.

Public contracts:
- WebhookBridgeSendRequest / WebhookBridgeSendResult
- WebhookBridgeAdapterError
- WebhookBridgeAdapterConfig / WebhookBridgeChannelAdapter
- send_via_webhook_bridge()
- webhook_bridge_payload_schema()
"""

from __future__ import annotations

import json
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

HttpMethod = Literal["POST", "PUT", "PATCH", "GET", "DELETE"]


class WebhookBridgeErrorInfo(TypedDict):
    code: str
    message: str
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WebhookBridgeAdapterConfig:
    url: str
    method: HttpMethod = "POST"
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_s: float = 10.0
    verify_tls: bool = True


@dataclass(frozen=True, slots=True)
class WebhookBridgeSendRequest:
    url: str
    payload: Mapping[str, Any]
    method: HttpMethod = "POST"
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_s: float = 10.0
    verify_tls: bool = True


@dataclass(frozen=True, slots=True)
class WebhookBridgeSendResult:
    ok: bool
    status_code: int | None
    response_text: str | None
    request_url: str
    method: str
    error: WebhookBridgeErrorInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status_code": self.status_code,
            "response_text": self.response_text,
            "request_url": self.request_url,
            "method": self.method,
            "error": self.error,
        }


class WebhookBridgeAdapterError(Exception):
    def __init__(self, *, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_error_info(self) -> WebhookBridgeErrorInfo:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


def _validate_url(url: str) -> None:
    if not isinstance(url, str) or not url.strip():
        raise WebhookBridgeAdapterError(code="missing_config", message="Webhook URL is required.", details={})
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WebhookBridgeAdapterError(
            code="invalid_url", message="Webhook URL must be an http(s) URL.", details={"url": url}
        )


def _normalize_method(method: str) -> str:
    if not isinstance(method, str) or not method.strip():
        raise WebhookBridgeAdapterError(code="invalid_method", message="HTTP method is required.", details={})
    m = method.strip().upper()
    allowed = {"POST", "PUT", "PATCH", "GET", "DELETE"}
    if m not in allowed:
        raise WebhookBridgeAdapterError(
            code="invalid_method",
            message="Unsupported HTTP method for webhook bridge.",
            details={"method": method, "allowed": sorted(allowed)},
        )
    return m


def _coerce_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if payload is None:
        raise WebhookBridgeAdapterError(code="invalid_payload", message="Webhook payload is required.", details={})
    if not isinstance(payload, Mapping):
        raise WebhookBridgeAdapterError(
            code="invalid_payload",
            message="Webhook payload must be a JSON object (mapping).",
            details={"payload_type": type(payload).__name__},
        )
    try:
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except TypeError as e:
        raise WebhookBridgeAdapterError(
            code="invalid_payload", message="Webhook payload must be JSON-serializable.", details={"error": str(e)}
        ) from e
    return payload


def _merge_headers(headers: Mapping[str, str]) -> dict[str, str]:
    base: dict[str, str] = {
        "Content-Type": "application/json",
        "User-Agent": "thomas-webhook-bridge/1.0",
    }
    if not headers:
        return base
    if not isinstance(headers, Mapping):
        raise WebhookBridgeAdapterError(
            code="invalid_headers",
            message="Headers must be a mapping.",
            details={"headers_type": type(headers).__name__},
        )
    for k, v in headers.items():
        if not isinstance(k, str) or not k.strip():
            raise WebhookBridgeAdapterError(
                code="invalid_headers",
                message="Header names must be non-empty strings.",
                details={"header_name": repr(k)},
            )
        if not isinstance(v, str):
            raise WebhookBridgeAdapterError(
                code="invalid_headers",
                message="Header values must be strings.",
                details={"header_name": k, "header_value_type": type(v).__name__},
            )
        base[k] = v
    return base


def _cap_text(text: str | None, cap: int = 500) -> str | None:
    if not isinstance(text, str):
        return text
    if len(text) <= cap:
        return text
    return text[:cap] + "…"


def send_via_webhook_bridge(req: WebhookBridgeSendRequest) -> WebhookBridgeSendResult:
    _validate_url(req.url)
    method = _normalize_method(req.method)
    payload = _coerce_payload(req.payload)

    if not isinstance(req.timeout_s, (int, float)) or float(req.timeout_s) <= 0:
        raise WebhookBridgeAdapterError(
            code="invalid_timeout", message="timeout_s must be a positive number.", details={"timeout_s": req.timeout_s}
        )

    headers = _merge_headers(req.headers)
    body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")

    # For GET/DELETE, some servers reject bodies. If payload is empty, omit body.
    data = body if (method not in ("GET", "DELETE") or body != b"{}") else None

    req_obj = urlrequest.Request(req.url, data=data, headers=headers, method=method)

    context = None
    if urlparse(req.url).scheme == "https" and not req.verify_tls:
        context = ssl._create_unverified_context()  # intentional opt-out
    try:
        with urlrequest.urlopen(req_obj, timeout=float(req.timeout_s), context=context) as resp:
            status = getattr(resp, "status", None)
            if status is None:
                status = resp.getcode()
            raw = resp.read(2048)
            try:
                text = raw.decode("utf-8", errors="replace")
            except (json.JSONDecodeError, ValueError, KeyError):
                text = None
    except urlerror.HTTPError as e:
        try:
            raw = e.read(2048)
            text = raw.decode("utf-8", errors="replace")
        except (json.JSONDecodeError, ValueError, KeyError):
            text = None
        raise WebhookBridgeAdapterError(
            code="non_success_status",
            message="Webhook returned a non-success HTTP status.",
            details={
                "status_code": int(getattr(e, "code", 0) or 0),
                "response_text": _cap_text(text),
                "url": req.url,
                "method": method,
            },
        ) from e
    except urlerror.URLError as e:
        raise WebhookBridgeAdapterError(
            code="request_failed",
            message="Webhook request failed.",
            details={"error": str(getattr(e, "reason", e)), "url": req.url, "method": method},
        ) from e
    except (ImportError, AttributeError, RuntimeError) as e:
        raise WebhookBridgeAdapterError(
            code="request_failed",
            message="Webhook request failed.",
            details={"error": str(e), "url": req.url, "method": method},
        ) from e

    status_code = int(status) if status is not None else None
    if status_code is None or not (200 <= status_code <= 299):
        raise WebhookBridgeAdapterError(
            code="non_success_status",
            message="Webhook returned a non-success HTTP status.",
            details={"status_code": status_code, "response_text": _cap_text(text), "url": req.url, "method": method},
        )

    return WebhookBridgeSendResult(
        ok=True,
        status_code=status_code,
        response_text=_cap_text(text),
        request_url=req.url,
        method=method,
        error=None,
    )


def webhook_bridge_payload_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Thomas Webhook Bridge Payload",
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Message text to deliver."},
            "metadata": {
                "type": "object",
                "description": "Optional structured metadata.",
                "additionalProperties": True,
            },
        },
        "required": ["text"],
        "additionalProperties": True,
    }


ADAPTER_ID = "webhook_bridge"


class WebhookBridgeChannelAdapter:
    def __init__(self, config: WebhookBridgeAdapterConfig) -> None:
        self._config = config

    @property
    def config(self) -> WebhookBridgeAdapterConfig:
        return self._config

    def send_text(self, text: str, *, metadata: Mapping[str, Any] | None = None) -> WebhookBridgeSendResult:
        payload: dict[str, Any] = {"text": text}
        if metadata is not None:
            payload["metadata"] = dict(metadata)

        req = WebhookBridgeSendRequest(
            url=self._config.url,
            payload=payload,
            method=self._config.method,
            headers=self._config.headers,
            timeout_s=self._config.timeout_s,
            verify_tls=self._config.verify_tls,
        )
        return send_via_webhook_bridge(req)


def register(registry: Any) -> None:
    if registry is None:
        return
    for method_name in ("register", "add", "add_adapter", "register_adapter"):
        fn = getattr(registry, method_name, None)
        if callable(fn):
            try:
                fn(ADAPTER_ID, WebhookBridgeChannelAdapter)
            except TypeError:
                fn(WebhookBridgeChannelAdapter)
            return
