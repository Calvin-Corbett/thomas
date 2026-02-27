"""P060 - Message pin command.

Thomas-native behavior:
    - Pin a message in a channel.
    - Idempotent: pinning an already pinned message should succeed.

This module defines the *core* contracts and behavior that both the CLI and (optionally)
server routes can call.

Backends
--------
Two backends are supported:

- ``memory``: deterministic in-memory store (useful for tests/dev)
- ``http``: call an external message service via HTTP JSON

Configuration
-------------
Environment variables (with a few tolerant aliases):

- THOMAS_MESSAGES_BACKEND / THOMAS_MESSAGE_BACKEND
    - 'memory' | 'http' (default: 'http')
- THOMAS_MESSAGES_API_URL / THOMAS_MESSAGE_API_URL
    - base URL for http backend (required when backend == 'http')
- THOMAS_MESSAGES_API_TOKEN / THOMAS_MESSAGE_API_TOKEN
    - bearer token (optional)
- THOMAS_MESSAGES_TIMEOUT_SECONDS / THOMAS_MESSAGE_TIMEOUT_SECONDS
    - request timeout in seconds (default: 10)

HTTP endpoint
-------------
The http backend posts to:

    {api_base_url.rstrip('/')}/messages/pin

The expected response JSON is flexible, but if present these keys are consumed:

- pinned: bool
- already_pinned: bool
- pin_id: str

If response JSON is missing/invalid, success is still reported for 2xx (and 409) responses
with a deterministic ``pin_id``.

"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, TypedDict

import requests

BackendType = Literal["memory", "http"]


# ----------------------------
# Contracts
# ----------------------------


@dataclass(frozen=True, slots=True)
class MessagePinInput:
    """Input contract for pinning a message."""

    channel_id: str
    message_id: str
    reason: str | None = None
    requested_by: str | None = None


@dataclass(frozen=True, slots=True)
class MessagePinResult:
    """Output contract for pinning a message."""

    pinned: bool
    already_pinned: bool
    channel_id: str
    message_id: str
    pin_id: str
    backend: BackendType


@dataclass(frozen=True, slots=True)
class MessagePinConfig:
    """Configuration contract for message pinning."""

    backend: BackendType = "http"
    api_base_url: str | None = None
    api_token: str | None = None
    timeout_seconds: float = 10.0


class MessagePinRequest(TypedDict, total=False):
    """Wire contract for JSON requests (CLI --json / webhook)."""

    channel_id: str
    message_id: str
    reason: str
    requested_by: str


class MessagePinErrorPayload(TypedDict):
    type: str
    code: str
    message: str
    details: dict[str, Any]


class MessagePinJsonSuccess(TypedDict):
    ok: Literal[True]
    result: dict[str, Any]


class MessagePinJsonFailure(TypedDict):
    ok: Literal[False]
    error: MessagePinErrorPayload


MessagePinJsonResponse = MessagePinJsonSuccess | MessagePinJsonFailure


# ----------------------------
# Errors (deterministic)
# ----------------------------


class MessagePinCommandError(Exception):
    """Base error type for message pin failures."""

    kind: str = "error"
    code: str = "error"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> MessagePinErrorPayload:
        return {
            "type": self.kind,
            "code": self.code,
            "message": str(self),
            "details": dict(self.details),
        }


class InvalidMessagePinInput(MessagePinCommandError):
    kind = "invalid_input"
    code = "invalid_input"


class MessagePinConfigError(MessagePinCommandError):
    kind = "config_error"
    code = "missing_config"


class MessagePinExternalError(MessagePinCommandError):
    kind = "external_error"
    code = "external_failure"


# ----------------------------
# In-memory backend
# ----------------------------


_MEMORY_PINS: dict[tuple[str, str], str] = {}


def reset_memory_pins() -> None:
    """Clear the in-memory pin store (useful for tests)."""

    _MEMORY_PINS.clear()


def _deterministic_pin_id(channel_id: str, message_id: str) -> str:
    digest = hashlib.sha256(f"{channel_id}:{message_id}".encode()).hexdigest()
    return f"mempin_{digest[:12]}"


# ----------------------------
# Helpers
# ----------------------------


def _env_get(env: Mapping[str, str], *keys: str) -> str | None:
    for k in keys:
        v = env.get(k)
        if v is None:
            continue
        v = v.strip()
        if v:
            return v
    return None


def load_message_pin_config(env: Mapping[str, str] | None = None) -> MessagePinConfig:
    """Load MessagePinConfig from environment.

    Raises:
        MessagePinConfigError: for missing/invalid config.
    """

    env = env or os.environ

    backend_raw = (_env_get(env, "THOMAS_MESSAGES_BACKEND", "THOMAS_MESSAGE_BACKEND") or "http").lower()

    if backend_raw in {"memory", "mem", "inmemory", "in-memory"}:
        backend: BackendType = "memory"
    elif backend_raw in {"http", "https"}:
        backend = "http"
    else:
        raise MessagePinConfigError(
            "Unsupported message backend.",
            details={"backend": backend_raw, "allowed": ["memory", "http"]},
        )

    api_base_url = _env_get(env, "THOMAS_MESSAGES_API_URL", "THOMAS_MESSAGE_API_URL")
    api_token = _env_get(env, "THOMAS_MESSAGES_API_TOKEN", "THOMAS_MESSAGE_API_TOKEN")

    timeout_raw = _env_get(env, "THOMAS_MESSAGES_TIMEOUT_SECONDS", "THOMAS_MESSAGE_TIMEOUT_SECONDS") or "10"
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as e:
        raise MessagePinConfigError(
            "Invalid message backend timeout.",
            details={"value": timeout_raw, "env": "THOMAS_MESSAGES_TIMEOUT_SECONDS"},
        ) from e

    if backend == "http" and not api_base_url:
        raise MessagePinConfigError(
            "Missing API base URL for http backend.",
            details={
                "missing": ["THOMAS_MESSAGES_API_URL"],
                "backend": backend,
            },
        )

    return MessagePinConfig(
        backend=backend,
        api_base_url=api_base_url,
        api_token=api_token,
        timeout_seconds=timeout_seconds,
    )


def _normalize_required_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidMessagePinInput(
            f"{field} must be a string.",
            details={"field": field, "received_type": type(value).__name__},
        )
    v = value.strip()
    if not v:
        raise InvalidMessagePinInput(
            f"{field} must not be empty.",
            details={"field": field},
        )
    return v


def _normalize_optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidMessagePinInput(
            f"{field} must be a string when provided.",
            details={"field": field, "received_type": type(value).__name__},
        )
    v = value.strip()
    return v or None


def parse_message_pin_request(payload: Mapping[str, Any]) -> MessagePinInput:
    """Parse and validate an incoming JSON-like mapping into MessagePinInput."""

    channel_id = _normalize_required_str(payload.get("channel_id"), "channel_id")
    message_id = _normalize_required_str(payload.get("message_id"), "message_id")
    reason = _normalize_optional_str(payload.get("reason"), "reason")
    requested_by = _normalize_optional_str(payload.get("requested_by"), "requested_by")

    return MessagePinInput(
        channel_id=channel_id,
        message_id=message_id,
        reason=reason,
        requested_by=requested_by,
    )


# ----------------------------
# Core behavior
# ----------------------------


def pin_message(
    pin_input: MessagePinInput,
    *,
    config: MessagePinConfig | None = None,
    http_post=requests.post,
) -> MessagePinResult:
    """Pin a message.

    Raises:
        InvalidMessagePinInput
        MessagePinConfigError
        MessagePinExternalError
    """

    channel_id = _normalize_required_str(pin_input.channel_id, "channel_id")
    message_id = _normalize_required_str(pin_input.message_id, "message_id")
    reason = _normalize_optional_str(pin_input.reason, "reason")
    requested_by = _normalize_optional_str(pin_input.requested_by, "requested_by")

    cfg = config or load_message_pin_config()

    if cfg.backend == "memory":
        key = (channel_id, message_id)
        existing = _MEMORY_PINS.get(key)
        if existing:
            return MessagePinResult(
                pinned=True,
                already_pinned=True,
                channel_id=channel_id,
                message_id=message_id,
                pin_id=existing,
                backend="memory",
            )

        pin_id = _deterministic_pin_id(channel_id, message_id)
        _MEMORY_PINS[key] = pin_id
        return MessagePinResult(
            pinned=True,
            already_pinned=False,
            channel_id=channel_id,
            message_id=message_id,
            pin_id=pin_id,
            backend="memory",
        )

    # http backend
    api_base_url = cfg.api_base_url
    if not api_base_url:
        # Defensive; load_message_pin_config should enforce.
        raise MessagePinConfigError(
            "Missing API base URL for http backend.",
            details={"missing": ["THOMAS_MESSAGES_API_URL"], "backend": "http"},
        )

    url = api_base_url.rstrip("/") + "/messages/pin"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg.api_token:
        headers["Authorization"] = f"Bearer {cfg.api_token}"

    payload: dict[str, Any] = {"channel_id": channel_id, "message_id": message_id}
    if reason:
        payload["reason"] = reason
    if requested_by:
        payload["requested_by"] = requested_by

    try:
        try:
            resp = http_post(url, headers=headers, json=payload, timeout=cfg.timeout_seconds)
        except TypeError:
            # Some injected callables may not accept `json=`.
            resp = http_post(
                url,
                headers=headers,
                data=json.dumps(payload),
                timeout=cfg.timeout_seconds,
            )
    except requests.RequestException as e:
        raise MessagePinExternalError(
            "Message backend request failed.",
            details={"exception": e.__class__.__name__},
        ) from e
    except (json.JSONDecodeError, ValueError, KeyError) as e:  # pragma: no cover
        raise MessagePinExternalError(
            "Unexpected error while calling message backend.",
            details={"exception": e.__class__.__name__},
        ) from e

    status = getattr(resp, "status_code", None)
    if status is None:
        raise MessagePinExternalError(
            "Message backend returned an invalid response object.",
            details={"missing": ["status_code"]},
        )

    text = getattr(resp, "text", "")

    # Treat 409 Conflict as idempotent 'already pinned' success.
    if status == 409:
        pin_id = _deterministic_pin_id(channel_id, message_id)
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("pin_id"):
                pin_id = str(data.get("pin_id"))
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
        return MessagePinResult(
            pinned=True,
            already_pinned=True,
            channel_id=channel_id,
            message_id=message_id,
            pin_id=pin_id,
            backend="http",
        )

    if status < 200 or status >= 300:
        raise MessagePinExternalError(
            "Message backend rejected pin request.",
            details={"status_code": status, "response_text": str(text)[:500]},
        )

    data: dict[str, Any] | None = None
    try:
        raw = resp.json()
        if isinstance(raw, dict):
            data = raw
    except (json.JSONDecodeError, ValueError, KeyError):
        data = None

    pinned = True
    already_pinned = False
    pin_id = _deterministic_pin_id(channel_id, message_id)

    if data is not None:
        pinned = bool(data.get("pinned", True))
        already_pinned = bool(data.get("already_pinned", False))
        if data.get("pin_id"):
            pin_id = str(data.get("pin_id"))

    return MessagePinResult(
        pinned=pinned,
        already_pinned=already_pinned,
        channel_id=channel_id,
        message_id=message_id,
        pin_id=pin_id,
        backend="http",
    )


def result_to_dict(result: MessagePinResult) -> dict[str, Any]:
    """Convert a MessagePinResult into a JSON-serializable dict."""

    return asdict(result)


def pin_message_json(
    payload: Mapping[str, Any],
    *,
    config: MessagePinConfig | None = None,
    http_post=requests.post,
) -> MessagePinJsonResponse:
    """Convenience wrapper that accepts a mapping and returns a machine-readable dict.

    This is useful for automation and server routes that prefer not to raise.
    """

    try:
        pin_input = parse_message_pin_request(payload)
        result = pin_message(pin_input, config=config, http_post=http_post)
        return {"ok": True, "result": result_to_dict(result)}
    except MessagePinCommandError as e:
        return {"ok": False, "error": e.to_dict()}
