"""Message poll creation (Thomas-native).

Creates a poll payload that can be emitted as a message (human-readable) and, optionally,
delivered to a configured webhook endpoint.

Principles:
- Deterministic, machine-readable success/failure shapes.
- Strict input validation with stable error codes.
- Optional external delivery (webhook POST) with predictable failure semantics.
- Minimal dependencies (stdlib HTTP by default), while allowing injection for tests.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

ERROR_INVALID_INPUT = "invalid_input"
ERROR_MISSING_CONFIG = "missing_config"
ERROR_EXTERNAL_FAILURE = "external_failure"
ERROR_INTERNAL = "internal_error"


class MessagePollCreateCommandError(Exception):
    """Base exception for message poll creation."""

    code: str
    details: dict[str, Any]

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    @property
    def message(self) -> str:
        return str(self)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class MessagePollInvalidInputError(MessagePollCreateCommandError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(ERROR_INVALID_INPUT, message, details=details)


class MessagePollMissingConfigError(MessagePollCreateCommandError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(ERROR_MISSING_CONFIG, message, details=details)


class MessagePollExternalFailureError(MessagePollCreateCommandError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(ERROR_EXTERNAL_FAILURE, message, details=details)


@dataclass(frozen=True, slots=True)
class MessagePollCreateInput:
    """Input contract for creating a poll."""

    question: str
    options: tuple[str, ...]
    channel: str | None = None
    target: str | None = None
    allow_multiple: bool = False
    anonymous: bool = False
    expires_in_seconds: int | None = None
    idempotency_key: str | None = None
    send: bool = False
    webhook_url: str | None = None
    base_url: str | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class MessagePollCreateOutput:
    """Output contract for creating a poll."""

    poll_id: str
    question: str
    options: tuple[str, ...]
    channel: str | None
    target: str | None
    allow_multiple: bool
    anonymous: bool
    expires_at: str | None
    message_text: str
    sent: bool
    delivery: dict[str, Any] | None
    poll_url: str | None

    def to_dict(self) -> dict[str, Any]:
        # Keep the JSON schema stable and automation-friendly.
        return {
            "poll_id": self.poll_id,
            "question": self.question,
            "options": list(self.options),
            "channel": self.channel,
            "target": self.target,
            "allow_multiple": self.allow_multiple,
            "anonymous": self.anonymous,
            "expires_at": self.expires_at,
            "message_text": self.message_text,
            "sent": self.sent,
            "delivery": self.delivery,
            "poll_url": self.poll_url,
        }


class _HttpResponse(Protocol):
    status_code: int
    text: str


def _normalize_question(question: str) -> str:
    q = (question or "").strip()
    if not q:
        raise MessagePollInvalidInputError("Question must be a non-empty string.")
    if len(q) > 500:
        raise MessagePollInvalidInputError(
            "Question is too long.",
            details={"max_length": 500, "actual_length": len(q)},
        )
    return q


def _normalize_options(options: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if options is None:
        raise MessagePollInvalidInputError("At least two options are required.")
    normed = tuple((o or "").strip() for o in options)
    normed = tuple(o for o in normed if o)
    if len(normed) < 2:
        raise MessagePollInvalidInputError(
            "At least two non-empty options are required.",
            details={"min_options": 2, "provided": len(normed)},
        )
    if len(normed) > 10:
        raise MessagePollInvalidInputError(
            "Too many options.",
            details={"max_options": 10, "provided": len(normed)},
        )
    lowered = [o.casefold() for o in normed]
    if len(set(lowered)) != len(lowered):
        raise MessagePollInvalidInputError("Options must be unique (case-insensitive).")
    too_long = [o for o in normed if len(o) > 100]
    if too_long:
        raise MessagePollInvalidInputError(
            "One or more options are too long.",
            details={"max_length": 100, "too_long": too_long[:5]},
        )
    return normed


def _normalize_channel(channel: str | None) -> str | None:
    if channel is None:
        return None
    c = channel.strip()
    if not c:
        return None
    if len(c) > 100:
        raise MessagePollInvalidInputError("channel is too long.", details={"max_length": 100})
    return c


def _normalize_target(target: str | None) -> str | None:
    if target is None:
        return None
    t = target.strip()
    if not t:
        return None
    if len(t) > 200:
        raise MessagePollInvalidInputError("target is too long.", details={"max_length": 200})
    return t


def _normalize_expires(expires_in_seconds: int | None) -> str | None:
    if expires_in_seconds is None:
        return None
    if not isinstance(expires_in_seconds, int):
        raise MessagePollInvalidInputError("expires_in_seconds must be an integer.")
    if expires_in_seconds <= 0:
        raise MessagePollInvalidInputError("expires_in_seconds must be > 0.")
    # Hard cap: 365 days.
    max_seconds = 365 * 24 * 60 * 60
    if expires_in_seconds > max_seconds:
        raise MessagePollInvalidInputError(
            "expires_in_seconds is too large.",
            details={"max_seconds": max_seconds, "provided": expires_in_seconds},
        )
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    return expires_at.isoformat().replace("+00:00", "Z")


def _normalize_idempotency_key(key: str | None) -> str | None:
    if key is None:
        return None
    if not isinstance(key, str):
        raise MessagePollInvalidInputError("idempotency_key must be a string.")
    k = key.strip()
    if not k:
        return None
    if len(k) > 200:
        raise MessagePollInvalidInputError(
            "idempotency_key is too long.",
            details={"max_length": 200, "actual_length": len(k)},
        )
    return k


def _build_poll_url(base_url: str | None, poll_id: str) -> str | None:
    if not base_url:
        return None
    base = base_url.strip()
    if not base:
        return None
    return f"{base.rstrip('/')}/polls/{poll_id}"


def _build_message_text(
    *,
    question: str,
    options: tuple[str, ...],
    poll_url: str | None,
    allow_multiple: bool,
    anonymous: bool,
    expires_at: str | None,
    channel: str | None,
    target: str | None,
) -> str:
    lines: list[str] = []
    if channel:
        lines.append(f"Channel: {channel}")
    if target:
        lines.append(f"Target: {target}")
    lines.append(f"Poll: {question}")
    for idx, opt in enumerate(options, start=1):
        lines.append(f"{idx}. {opt}")

    meta_bits: list[str] = []
    if allow_multiple:
        meta_bits.append("multiple choice")
    if anonymous:
        meta_bits.append("anonymous")
    if expires_at:
        meta_bits.append(f"expires {expires_at}")
    if meta_bits:
        lines.append(f"({', '.join(meta_bits)})")
    if poll_url:
        lines.append(f"Vote: {poll_url}")
    return "\n".join(lines)


def _resolve_webhook_url(explicit: str | None) -> str | None:
    if explicit and explicit.strip():
        return explicit.strip()
    # Environment variables are intentionally simple and deterministic.
    for key in ("THOMAS_MESSAGE_WEBHOOK_URL", "THOMAS_MESSAGING_WEBHOOK_URL", "THOMAS_WEBHOOK_URL"):
        val = os.getenv(key)
        if val and val.strip():
            return val.strip()
    return None


def _stdlib_post(url: str, *, json: dict[str, Any], timeout: float) -> _HttpResponse:
    """Default HTTP POST implementation using stdlib urllib."""

    data = jsonlib_dumps(json).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    class _R:
        def __init__(self, status_code: int, text: str):
            self.status_code = status_code
            self.text = text

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - user provided URL by design
            status = int(getattr(resp, "status", 200))
            body = resp.read().decode("utf-8", errors="replace")
            return _R(status, body)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except (json.JSONDecodeError, ValueError, KeyError):
            body = ""
        return _R(int(e.code), body)
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        # Bubble up; caller wraps deterministically.
        raise exc


def jsonlib_dumps(obj: Any) -> str:
    # One place to standardize JSON encoding.
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def run(
    inp: MessagePollCreateInput,
    *,
    http_timeout_seconds: float = 10.0,
    _post=_stdlib_post,
) -> MessagePollCreateOutput:
    """Create a poll and (optionally) deliver it via webhook.

    Deterministic error policy:
    - Invalid input -> MessagePollInvalidInputError
    - Missing config needed for delivery -> MessagePollMissingConfigError
    - Delivery/network errors -> MessagePollExternalFailureError
    """

    try:
        question = _normalize_question(inp.question)
        options = _normalize_options(list(inp.options))
        expires_at = _normalize_expires(inp.expires_in_seconds)
        idem_key = _normalize_idempotency_key(inp.idempotency_key)
        channel = _normalize_channel(inp.channel)
        target = _normalize_target(inp.target)
    except MessagePollCreateCommandError:
        raise
    except (ConnectionError, TimeoutError, RuntimeError) as exc:  # pragma: no cover
        raise MessagePollCreateCommandError(ERROR_INTERNAL, "Failed to validate poll input.") from exc

    poll_id = uuid.uuid5(uuid.NAMESPACE_URL, idem_key).hex if idem_key else uuid.uuid4().hex
    poll_url = _build_poll_url(inp.base_url, poll_id)
    message_text = _build_message_text(
        question=question,
        options=options,
        poll_url=poll_url,
        allow_multiple=bool(inp.allow_multiple),
        anonymous=bool(inp.anonymous),
        expires_at=expires_at,
        channel=channel,
        target=target,
    )

    delivery: dict[str, Any] | None = None
    should_send = bool(inp.send)
    if should_send:
        webhook_url = _resolve_webhook_url(inp.webhook_url)
        if not webhook_url:
            raise MessagePollMissingConfigError(
                "No webhook URL configured for delivery.",
                details={"how_to_fix": "Pass --webhook-url or set THOMAS_WEBHOOK_URL (or THOMAS_MESSAGE_WEBHOOK_URL)."},
            )

        payload: dict[str, Any] = {
            "text": message_text,
            "thomas": {
                "kind": "message_poll",
                "poll": {
                    "poll_id": poll_id,
                    "question": question,
                    "options": list(options),
                    "allow_multiple": bool(inp.allow_multiple),
                    "anonymous": bool(inp.anonymous),
                    "expires_at": expires_at,
                    "poll_url": poll_url,
                    "channel": channel,
                    "target": target,
                    "metadata": dict(inp.metadata or {}),
                },
            },
        }

        try:
            resp = _post(webhook_url, json=payload, timeout=float(http_timeout_seconds))
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            raise MessagePollExternalFailureError(
                "Failed to deliver poll via webhook.",
                details={"exception": exc.__class__.__name__},
            ) from exc

        status = int(getattr(resp, "status_code", 0) or 0)
        text = (getattr(resp, "text", "") or "").strip()
        if len(text) > 500:
            text = text[:500] + "…"

        if not (200 <= status < 300):
            raise MessagePollExternalFailureError(
                "Webhook delivery failed.",
                details={"status_code": status, "response": text},
            )

        delivery = {"status_code": status, "response": text}

    return MessagePollCreateOutput(
        poll_id=poll_id,
        question=question,
        options=options,
        channel=channel,
        target=target,
        allow_multiple=bool(inp.allow_multiple),
        anonymous=bool(inp.anonymous),
        expires_at=expires_at,
        message_text=message_text,
        sent=should_send,
        delivery=delivery,
        poll_url=poll_url,
    )


def run_json(inp: MessagePollCreateInput, **kwargs: Any) -> str:
    """Automation helper: returns a JSON string (success or error)."""

    try:
        out = run(inp, **kwargs)
        payload = {"ok": True, "poll": out.to_dict()}
    except MessagePollCreateCommandError as exc:
        payload = {"ok": False, "error": exc.to_dict()}
    return json.dumps(payload, sort_keys=True)


class MessagePollCreateCommand:
    """Thin OO wrapper for codepaths that prefer a command-object style."""

    @staticmethod
    def run(inp: MessagePollCreateInput, **kwargs: Any) -> MessagePollCreateOutput:
        return run(inp, **kwargs)
