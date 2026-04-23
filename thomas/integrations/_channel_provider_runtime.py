"""Shared sync helpers for channel provider wrappers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 5.0


def as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    return {}


def text_value(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def build_message_text(message: str, *, subject: str | None = None) -> str:
    body = str(message or "").strip()
    title = str(subject or "").strip()
    if title and body:
        return f"{title}\n\n{body}"
    return title or body


def resolve_request_payload(
    request: Any = None,
    *,
    config: Mapping[str, Any] | None = None,
    recipient: str | None = None,
    message: str | None = None,
    text: str | None = None,
    subject: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    timeout_seconds: float | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "config": as_mapping(config),
        "recipient": text_value(recipient),
        "message": text_value(message, text),
        "subject": text_value(subject),
        "metadata": as_mapping(metadata),
        "timeout_seconds": float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
        "dry_run": bool(dry_run),
    }

    if request is None:
        return payload

    if hasattr(request, "recipient"):
        payload["recipient"] = text_value(getattr(request, "recipient", None), payload["recipient"])
    if hasattr(request, "message"):
        payload["message"] = text_value(getattr(request, "message", None), payload["message"])
    if hasattr(request, "subject"):
        payload["subject"] = text_value(getattr(request, "subject", None), payload["subject"])
    if hasattr(request, "metadata"):
        payload["metadata"] = {**as_mapping(getattr(request, "metadata", None)), **payload["metadata"]}
    if hasattr(request, "timeout_seconds"):
        value = getattr(request, "timeout_seconds", None)
        if value not in (None, ""):
            payload["timeout_seconds"] = float(value)
    if hasattr(request, "dry_run"):
        payload["dry_run"] = bool(getattr(request, "dry_run", False))
    return payload


def http_json_request(
    method: str,
    url: str,
    *,
    payload: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    req = urllib.request.Request(
        url=url,
        data=(json.dumps(dict(payload)).encode("utf-8") if payload is not None else None),
        headers={"Content-Type": "application/json", **dict(headers or {})},
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:  # nosec B310
            body = response.read()
            status = int(getattr(response, "status", 0) or 0)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = int(getattr(exc, "code", 0) or 0)
        return {
            "ok": False,
            "status": status,
            "payload": _decode_response_body(body),
            "error": f"HTTPError: {status}",
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "status": 0,
            "payload": {},
            "error": f"URLError: {exc.reason}",
        }
    except TimeoutError as exc:
        return {
            "ok": False,
            "status": 0,
            "payload": {},
            "error": f"timeout: {exc}",
        }

    return {
        "ok": 200 <= status < 300,
        "status": status,
        "payload": _decode_response_body(body),
        "error": "",
    }


def _decode_response_body(body: bytes) -> Any:
    raw = body.decode("utf-8", errors="replace")
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
