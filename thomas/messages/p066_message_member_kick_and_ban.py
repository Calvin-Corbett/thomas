"""P066 - Moderate a channel member by kicking or banning them.

Thomas-native behavior:
- Validates a request payload (from CLI or webhook router).
- Calls a configured outbound webhook to perform the moderation action.
- Produces deterministic, machine-readable success/failure outputs.

Why a webhook?
Thomas shouldn't hardcode vendor-specific moderation APIs in this prompt-pack lane.
The outbound webhook is an integration seam: Slack/Discord/Matrix/etc. can live behind it.

Public entrypoints:
- parse_request(payload) -> MemberModerationRequest
- execute(request, webhook_url=..., ...) -> MemberModerationResult
- run(payload, config=..., webhook_url=...) -> dict (JSON-serialisable)
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, Union, cast

import requests

ModerationAction = Literal["kick", "ban"]


# -----------------------------
# Errors (deterministic)
# -----------------------------


class MemberModerationError(Exception):
    """Base deterministic error with a stable machine-readable code."""

    code: str
    details: dict[str, Any]

    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_failure_dict(self) -> MemberModerationFailure:
        return {
            "ok": False,
            "error": {"code": self.code, "message": str(self), "details": self.details},
        }


class InvalidInputError(MemberModerationError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(code="invalid_input", message=message, details=details)


class MissingConfigError(MemberModerationError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(code="missing_config", message=message, details=details)


class ExternalServiceError(MemberModerationError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(code="external_failure", message=message, details=details)


# -----------------------------
# Contracts
# -----------------------------


class MemberModerationRequestDict(TypedDict, total=False):
    action: str
    channel_id: str
    member_id: str
    reason: str
    webhook_url: str
    timeout_s: int | float
    request_id: str
    metadata: dict[str, Any]


class MemberModerationSuccess(TypedDict):
    ok: Literal[True]
    action: ModerationAction
    channel_id: str
    member_id: str
    message: str
    provider_response: Mapping[str, Any] | None
    request_id: str | None


class MemberModerationFailure(TypedDict):
    ok: Literal[False]
    error: dict[str, Any]
    request_id: str | None


MemberModerationResponse = Union[MemberModerationSuccess, MemberModerationFailure]


@dataclass(frozen=True)
class MemberModerationRequest:
    action: ModerationAction
    channel_id: str
    member_id: str
    reason: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class MemberModerationResult:
    action: ModerationAction
    channel_id: str
    member_id: str
    message: str
    provider_response: Mapping[str, Any] | None = None
    request_id: str | None = None

    def to_success_dict(self) -> MemberModerationSuccess:
        return {
            "ok": True,
            "action": self.action,
            "channel_id": self.channel_id,
            "member_id": self.member_id,
            "message": self.message,
            "provider_response": self.provider_response,
            "request_id": self.request_id,
        }


# -----------------------------
# Parsing + normalization
# -----------------------------


_ACTION_ALIASES: dict[str, ModerationAction] = {
    "kick": "kick",
    "kicked": "kick",
    "remove": "kick",
    "removed": "kick",
    "eject": "kick",
    "ban": "ban",
    "banned": "ban",
    "block": "ban",
    "blocked": "ban",
}

_CHANNEL_KEYS: Sequence[str] = (
    "channel_id",
    "channel",
    "channelId",
    "conversation_id",
    "conversationId",
    "room_id",
    "roomId",
    "server_id",
    "serverId",
    "guild_id",
    "guildId",
)

_MEMBER_KEYS: Sequence[str] = (
    "member_id",
    "memberId",
    "member",
    "user_id",
    "userId",
    "user",
    "username",
    "handle",
)

_ACTION_KEYS: Sequence[str] = ("action", "operation", "mode")
_REASON_KEYS: Sequence[str] = ("reason", "note", "comment", "message")
_REQUEST_ID_KEYS: Sequence[str] = ("request_id", "requestId", "rid", "trace_id", "traceId")


def _unwrap_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    # Some webhook routers nest user payload under common keys.
    for k in ("payload", "data", "body"):
        v = payload.get(k)
        if isinstance(v, Mapping):
            # Keep top-level as fallback by shallow-merge.
            merged = dict(payload)
            merged.update(v)
            return merged
    return payload


def _first_str(payload: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _norm_id(value: str, *, field: str) -> str:
    s = value.strip()
    if not s:
        raise InvalidInputError(f"{field} is required")
    if len(s) > 256:
        raise InvalidInputError(f"{field} is too long", details={"max": 256, "got_len": len(s)})
    return s


def parse_request(payload: Mapping[str, Any]) -> MemberModerationRequest:
    """Validate and normalise untrusted input into a strongly-typed request."""

    if not isinstance(payload, Mapping):
        raise InvalidInputError("payload must be an object", details={"got": type(payload).__name__})

    payload_u = _unwrap_payload(payload)

    raw_action = _first_str(payload_u, _ACTION_KEYS)
    if not raw_action:
        raise InvalidInputError("action is required", details={"allowed": ["kick", "ban"]})
    action = _ACTION_ALIASES.get(raw_action.lower())
    if action not in ("kick", "ban"):
        raise InvalidInputError(
            "action must be 'kick' or 'ban'",
            details={"got": raw_action, "allowed": ["kick", "ban"]},
        )

    channel_raw = _first_str(payload_u, _CHANNEL_KEYS)
    if not channel_raw:
        raise InvalidInputError("channel_id is required", details={"expected_keys": list(_CHANNEL_KEYS)})
    channel_id = _norm_id(channel_raw, field="channel_id")

    member_raw = _first_str(payload_u, _MEMBER_KEYS)
    if not member_raw:
        raise InvalidInputError("member_id is required", details={"expected_keys": list(_MEMBER_KEYS)})
    member_id = _norm_id(member_raw, field="member_id")

    reason = _first_str(payload_u, _REASON_KEYS)
    reason_str = reason.strip() if isinstance(reason, str) and reason.strip() else None

    request_id = _first_str(payload_u, _REQUEST_ID_KEYS)
    request_id_str = request_id.strip() if isinstance(request_id, str) and request_id.strip() else None

    metadata = payload_u.get("metadata")
    if metadata is not None and not isinstance(metadata, Mapping):
        raise InvalidInputError("metadata must be an object", details={"got": type(metadata).__name__})

    return MemberModerationRequest(
        action=cast(ModerationAction, action),
        channel_id=channel_id,
        member_id=member_id,
        reason=reason_str,
        request_id=request_id_str,
        metadata=cast(Mapping[str, Any] | None, metadata),
    )


# -----------------------------
# Config + execution
# -----------------------------


def _truncate(text: str, limit: int = 800) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _default_success_message(action: ModerationAction, member_id: str, channel_id: str) -> str:
    verb = "kicked" if action == "kick" else "banned"
    return f"Member {member_id} {verb} from channel {channel_id}."


def _get_from_config(config: Any, key: str) -> Any:
    if config is None:
        return None
    if isinstance(config, Mapping):
        return config.get(key)
    return getattr(config, key, None)


def _resolve_webhook_url(
    explicit_url: str | None,
    *,
    payload: Mapping[str, Any] | None = None,
    config: Any | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    if isinstance(explicit_url, str) and explicit_url.strip():
        return explicit_url.strip()

    payload = payload or {}
    candidate = payload.get("webhook_url")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()

    for k in (
        "messages_member_moderation_webhook_url",
        "messages_moderation_webhook_url",
        "messages_webhook_url",
        "webhook_url",
    ):
        v = _get_from_config(config, k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    env = env or os.environ
    for k in (
        "THOMAS_MESSAGES_MEMBER_MODERATION_WEBHOOK_URL",
        "THOMAS_MESSAGES_MODERATION_WEBHOOK_URL",
        "THOMAS_MESSAGES_WEBHOOK_URL",
        "THOMAS_WEBHOOK_URL",
    ):
        v = env.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    raise MissingConfigError(
        "No webhook URL configured for member moderation",
        details={
            "expected_payload_key": "webhook_url",
            "expected_env": [
                "THOMAS_MESSAGES_MEMBER_MODERATION_WEBHOOK_URL",
                "THOMAS_MESSAGES_MODERATION_WEBHOOK_URL",
                "THOMAS_MESSAGES_WEBHOOK_URL",
            ],
            "expected_config_keys": [
                "messages_member_moderation_webhook_url",
                "messages_moderation_webhook_url",
                "messages_webhook_url",
            ],
        },
    )


def execute(
    request: MemberModerationRequest,
    *,
    webhook_url: str,
    timeout_s: float = 10.0,
    session: requests.Session | None = None,
    extra_headers: Mapping[str, str] | None = None,
) -> MemberModerationResult:
    """Kick or ban a member by calling the configured webhook."""

    if not isinstance(webhook_url, str) or not webhook_url.strip():
        raise MissingConfigError("webhook_url is required")
    if not isinstance(timeout_s, (int, float)) or float(timeout_s) <= 0:
        raise InvalidInputError("timeout_s must be a positive number", details={"got": timeout_s})

    outbound_payload: dict[str, Any] = {
        "action": request.action,
        "channel_id": request.channel_id,
        "member_id": request.member_id,
    }
    if request.reason:
        outbound_payload["reason"] = request.reason
    if request.request_id:
        outbound_payload["request_id"] = request.request_id
    if request.metadata:
        outbound_payload["metadata"] = dict(request.metadata)

    headers: dict[str, str] = {"Accept": "application/json"}
    if request.request_id:
        headers["X-Thomas-Request-Id"] = request.request_id
    if extra_headers:
        for k, v in extra_headers.items():
            if isinstance(k, str) and isinstance(v, str) and k.strip():
                headers[k] = v

    client: Any = session if session is not None else requests

    try:
        resp = client.post(webhook_url.strip(), json=outbound_payload, timeout=float(timeout_s), headers=headers)
    except requests.RequestException as exc:
        raise ExternalServiceError(
            "Failed to reach member moderation webhook",
            details={"exception": repr(exc)},
        ) from exc

    if resp.status_code < 200 or resp.status_code >= 300:
        try:
            body_preview = _truncate(resp.text or "")
        except (json.JSONDecodeError, ValueError, KeyError):
            body_preview = "<unreadable>"
        raise ExternalServiceError(
            "Member moderation webhook returned a non-success status",
            details={"status_code": resp.status_code, "body": body_preview},
        )

    provider_response: Mapping[str, Any] | None = None
    try:
        provider_response = cast(Mapping[str, Any], resp.json())
    except ValueError:
        text = ""
        try:
            text = resp.text or ""
        except (json.JSONDecodeError, ValueError, KeyError):
            text = ""
        provider_response = {"raw": _truncate(text)} if text else None

    message: str
    if isinstance(provider_response, Mapping) and isinstance(provider_response.get("message"), str):
        message = cast(str, provider_response.get("message"))
    else:
        message = _default_success_message(request.action, request.member_id, request.channel_id)

    return MemberModerationResult(
        action=request.action,
        channel_id=request.channel_id,
        member_id=request.member_id,
        message=message,
        provider_response=provider_response,
        request_id=request.request_id,
    )


def run(
    payload: Mapping[str, Any],
    config: Any | None = None,
    webhook_url: str | None = None,
    session: requests.Session | None = None,
) -> MemberModerationResponse:
    """Automation-friendly wrapper.

    Returns only JSON-serialisable data. Never raises on expected failures.
    """

    request_id: str | None = None
    try:
        request = parse_request(payload)
        request_id = request.request_id

        resolved_webhook_url = _resolve_webhook_url(webhook_url, payload=_unwrap_payload(payload), config=config)

        timeout_raw = _unwrap_payload(payload).get("timeout_s", 10.0)
        try:
            timeout_s = float(timeout_raw)  # type: ignore[arg-type]
        except (json.JSONDecodeError, ValueError, KeyError):
            raise InvalidInputError("timeout_s must be a number", details={"got": timeout_raw})

        extra_headers = _get_from_config(config, "messages_member_moderation_extra_headers")
        if extra_headers is not None and not isinstance(extra_headers, Mapping):
            raise InvalidInputError("messages_member_moderation_extra_headers must be an object")

        result = execute(
            request,
            webhook_url=resolved_webhook_url,
            timeout_s=timeout_s,
            session=session,
            extra_headers=cast(Mapping[str, str] | None, extra_headers),
        )
        return result.to_success_dict()
    except MemberModerationError as exc:
        out = exc.to_failure_dict()
        out["request_id"] = request_id
        return cast(MemberModerationFailure, out)
    except (ConnectionError, TimeoutError, RuntimeError) as exc:  # pragma: no cover
        out = ExternalServiceError("Unhandled failure", details={"exception": repr(exc)}).to_failure_dict()
        out["request_id"] = request_id
        return cast(MemberModerationFailure, out)


def handle_webhook(payload: Mapping[str, Any], config: Any | None = None) -> MemberModerationResponse:
    """Convenience for server webhook routers: same contract as `run()`."""
    return run(payload, config=config)


__all__ = [
    "ModerationAction",
    "MemberModerationError",
    "InvalidInputError",
    "MissingConfigError",
    "ExternalServiceError",
    "MemberModerationRequest",
    "MemberModerationResult",
    "MemberModerationRequestDict",
    "MemberModerationResponse",
    "parse_request",
    "execute",
    "run",
    "handle_webhook",
]
