"""Message delivery primitives used by the Thomas CLI.

Prompt P074 adds a Thomas-native `messages` CLI group and a minimal, explicit
delivery contract. This is deliberately small but *predictable*: errors are
deterministic and machine-readable for automation.

Delivery mechanism:
  - HTTP POST JSON to a configured webhook URL (env or CLI override).

Note:
  - The webhook target can be a 3rd-party integration or a Thomas server route
    (e.g. a local `/webhooks/...` endpoint) depending on your deployment.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import httpx

JsonDict = dict[str, Any]

_ENV_WEBHOOK_URL = "THOMAS_MESSAGE_WEBHOOK_URL"
_ENV_TIMEOUT_SECONDS = "THOMAS_MESSAGE_TIMEOUT_SECONDS"


class MessageIntegrationError(Exception):
    """Base error for message integration failures."""

    def __init__(self, message: str, *, code: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details: JsonDict = dict(details or {})

    def to_dict(self) -> JsonDict:
        return {"code": self.code, "message": str(self), "details": self.details}


class InvalidMessageInputError(MessageIntegrationError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message, code="invalid_input", details=details)


class MessageConfigError(MessageIntegrationError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message, code="missing_config", details=details)


class MessageDeliveryError(MessageIntegrationError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message, code="delivery_failed", details=details)


@dataclass(frozen=True, slots=True)
class MessageDeliveryConfig:
    webhook_url: str
    timeout_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class MessageSendRequest:
    channel: str
    text: str
    metadata: JsonDict = field(default_factory=dict)
    message_id: str | None = None  # optional override for idempotency


@dataclass(frozen=True, slots=True)
class MessageSendResult:
    message_id: str
    channel: str
    text: str
    delivered: bool
    delivered_at: str
    provider: str
    response_status: int | None = None

    def to_dict(self) -> JsonDict:
        return {
            "message_id": self.message_id,
            "channel": self.channel,
            "text": self.text,
            "delivered": self.delivered,
            "delivered_at": self.delivered_at,
            "provider": self.provider,
            "response_status": self.response_status,
        }


def load_message_delivery_config(
    *,
    env: Mapping[str, str] | None = None,
    webhook_url: str | None = None,
    timeout_seconds: float | None = None,
) -> MessageDeliveryConfig:
    """Load delivery config from explicit args and/or environment."""

    env_map = dict(os.environ) if env is None else dict(env)

    resolved_url = (webhook_url or "").strip() or env_map.get(_ENV_WEBHOOK_URL, "").strip()
    if not resolved_url:
        raise MessageConfigError(
            "No message webhook URL configured.",
            details={"expected_env": _ENV_WEBHOOK_URL},
        )

    if timeout_seconds is not None:
        resolved_timeout = float(timeout_seconds)
    else:
        raw = env_map.get(_ENV_TIMEOUT_SECONDS, "").strip()
        if raw:
            try:
                resolved_timeout = float(raw)
            except ValueError as e:
                raise InvalidMessageInputError(
                    "Invalid timeout value.",
                    details={"env": _ENV_TIMEOUT_SECONDS, "value": raw},
                ) from e
        else:
            resolved_timeout = 5.0

    if resolved_timeout <= 0:
        raise InvalidMessageInputError(
            "Timeout must be positive.",
            details={"timeout_seconds": resolved_timeout},
        )

    return MessageDeliveryConfig(webhook_url=resolved_url, timeout_seconds=resolved_timeout)


def validate_send_request(req: MessageSendRequest) -> None:
    channel = (req.channel or "").strip()
    if not channel:
        raise InvalidMessageInputError("Channel is required.", details={"field": "channel"})

    text = (req.text or "").strip()
    if not text:
        raise InvalidMessageInputError("Text is required.", details={"field": "text"})

    # Small guardrail: helps prevent accidental megabyte blasts from scripts.
    if len(text) > 10_000:
        raise InvalidMessageInputError(
            "Text is too long.",
            details={"field": "text", "max_length": 10_000, "length": len(text)},
        )

    if req.message_id is not None:
        mid = req.message_id.strip()
        if not mid:
            raise InvalidMessageInputError("message_id cannot be empty.", details={"field": "message_id"})


def build_webhook_payload(req: MessageSendRequest, *, message_id: str) -> JsonDict:
    return {
        "id": message_id,
        "channel": req.channel,
        "text": req.text,
        "metadata": req.metadata,
    }


def _default_post_json(url: str, payload: JsonDict, *, timeout_seconds: float) -> httpx.Response:
    with httpx.Client(timeout=timeout_seconds) as client:
        return client.post(url, json=payload)


def send_message(
    req: MessageSendRequest,
    config: MessageDeliveryConfig,
    *,
    post_json: Callable[[str, JsonDict, float], httpx.Response] | None = None,
) -> MessageSendResult:
    """Send a message using the configured delivery mechanism."""

    validate_send_request(req)

    message_id = (req.message_id or "").strip() or str(uuid.uuid4())
    payload = build_webhook_payload(req, message_id=message_id)

    post = post_json
    if post is None:
        def post(url: str, payload: JsonDict, timeout_seconds: float) -> httpx.Response:  # type: ignore[misc]
            return _default_post_json(url, payload, timeout_seconds=timeout_seconds)

    try:
        resp = post(config.webhook_url, payload, config.timeout_seconds)
    except httpx.TimeoutException as e:
        raise MessageDeliveryError(
            "Message delivery timed out.",
            details={"webhook_url": config.webhook_url, "timeout_seconds": config.timeout_seconds},
        ) from e
    except httpx.HTTPError as e:
        raise MessageDeliveryError(
            "Message delivery failed.",
            details={
                "webhook_url": config.webhook_url,
                "error": e.__class__.__name__,
            },
        ) from e

    if resp.status_code < 200 or resp.status_code >= 300:
        body_preview = (resp.text or "")[:500]
        raise MessageDeliveryError(
            "Message delivery returned a non-success status.",
            details={
                "webhook_url": config.webhook_url,
                "status_code": resp.status_code,
                "response_text": body_preview,
            },
        )

    delivered_at = datetime.now(timezone.utc).isoformat()
    return MessageSendResult(
        message_id=message_id,
        channel=req.channel,
        text=req.text,
        delivered=True,
        delivered_at=delivered_at,
        provider="webhook",
        response_status=resp.status_code,
    )
