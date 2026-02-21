"""P065 - Message member timeout.

Thomas-native behavior: apply a temporary communication restriction ("timeout") to a
member on a chat platform that supports this concept.

Primary target: Discord's `communication_disabled_until` member field.

Design goals:
- no network/config work at import time
- deterministic, machine-readable errors
- injectable HTTP client for tests
- tolerant payload parsing for upstream automations (small alias set)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, MutableMapping, NotRequired, Protocol, TypedDict
from urllib.parse import quote

DEFAULT_API_BASE_URL = "https://discord.com/api/v10"
# Discord max timeout: 28 days
MAX_TIMEOUT_SECONDS = 28 * 24 * 60 * 60


class MessageMemberTimeoutError(Exception):
    """Base error for this operation.

    `code` is stable and intended for automation.
    """

    code: str
    message: str
    details: dict[str, Any]

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


class InvalidInputError(MessageMemberTimeoutError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("INVALID_INPUT", message, details=details)


class MissingConfigError(MessageMemberTimeoutError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("MISSING_CONFIG", message, details=details)


class ExternalServiceError(MessageMemberTimeoutError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("EXTERNAL_FAILURE", message, details=details)


class _HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> Any:  # pragma: no cover
        ...


class HttpRequester(Protocol):
    def __call__(
        self,
        method: str,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> _HttpResponse:
        ...


class MessageMemberTimeoutPayload(TypedDict):
    guild_id: str
    user_id: str
    duration_seconds: int
    reason: NotRequired[str]
    message_id: NotRequired[str]


class MessageMemberTimeoutConfigDict(TypedDict, total=False):
    bot_token: str
    api_base_url: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class MessageMemberTimeoutRequest:
    guild_id: str
    user_id: str
    duration_seconds: int
    reason: str | None = None
    message_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "duration_seconds": self.duration_seconds,
        }
        if self.reason is not None:
            out["reason"] = self.reason
        if self.message_id is not None:
            out["message_id"] = self.message_id
        return out


@dataclass(frozen=True, slots=True)
class MessageMemberTimeoutConfig:
    bot_token: str
    api_base_url: str = DEFAULT_API_BASE_URL
    timeout_seconds: float = 10.0


@dataclass(frozen=True, slots=True)
class MessageMemberTimeoutResult:
    guild_id: str
    user_id: str
    duration_seconds: int
    timed_out_until: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "duration_seconds": self.duration_seconds,
            "timed_out_until": self.timed_out_until,
        }


def _iso8601_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _require_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(
            f"Field '{key}' must be a non-empty string.",
            details={"field": key},
        )
    return value.strip()


def _require_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise InvalidInputError(f"Field '{key}' must be an integer.", details={"field": key})
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        # tolerate numeric strings from upstream automation payloads
        try:
            return int(value.strip(), 10)
        except Exception:
            pass
    raise InvalidInputError(f"Field '{key}' must be an integer.", details={"field": key})


def _validate_snowflake(field: str, value: str) -> None:
    # Discord IDs are numeric strings.
    if not value.isdigit():
        raise InvalidInputError(
            f"Field '{field}' must be a numeric string.",
            details={"field": field},
        )


def _validate_request(req: MessageMemberTimeoutRequest) -> None:
    _validate_snowflake("guild_id", req.guild_id)
    _validate_snowflake("user_id", req.user_id)
    if req.message_id is not None:
        _validate_snowflake("message_id", req.message_id)

    if req.duration_seconds <= 0:
        raise InvalidInputError(
            "Field 'duration_seconds' must be greater than zero.",
            details={"field": "duration_seconds"},
        )
    if req.duration_seconds > MAX_TIMEOUT_SECONDS:
        raise InvalidInputError(
            f"Field 'duration_seconds' must be <= {MAX_TIMEOUT_SECONDS}.",
            details={"field": "duration_seconds", "max": MAX_TIMEOUT_SECONDS},
        )

    if req.reason is not None:
        if not isinstance(req.reason, str):
            raise InvalidInputError("Field 'reason' must be a string.", details={"field": "reason"})
        if len(req.reason) > 512:
            raise InvalidInputError(
                "Field 'reason' must be <= 512 characters.",
                details={"field": "reason", "max": 512},
            )


def _validate_config(cfg: MessageMemberTimeoutConfig) -> None:
    if not isinstance(cfg.bot_token, str) or not cfg.bot_token.strip():
        raise MissingConfigError(
            "Missing required configuration: bot_token.",
            details={"missing": "bot_token"},
        )
    if not isinstance(cfg.api_base_url, str) or not cfg.api_base_url.strip():
        raise MissingConfigError(
            "Missing required configuration: api_base_url.",
            details={"missing": "api_base_url"},
        )
    if not isinstance(cfg.timeout_seconds, (int, float)) or float(cfg.timeout_seconds) <= 0:
        raise InvalidInputError(
            "Field 'timeout_seconds' must be a positive number.",
            details={"field": "timeout_seconds"},
        )


def _default_http_request(
    method: str,
    url: str,
    *,
    json: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> _HttpResponse:
    # Local import so importing this module does not require requests.
    import requests

    return requests.request(method, url, json=json, headers=headers, timeout=timeout)


def _safe_trim(text: str, limit: int = 400) -> str:
    s = text or ""
    if len(s) > limit:
        return s[:limit] + "..."
    return s


def _extract_error_details(resp: _HttpResponse) -> dict[str, Any]:
    # Discord error payloads usually include keys like `message`, `code`, `errors`.
    details: dict[str, Any] = {}
    raw_text = getattr(resp, "text", "") or ""
    details["response"] = _safe_trim(raw_text, 400)
    try:
        data = resp.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        # Only surface a small stable subset to keep outputs deterministic.
        for k in ("message", "code", "errors"):
            if k in data:
                details[f"discord_{k}"] = data.get(k)
    return details


def timeout_member(
    req: MessageMemberTimeoutRequest,
    cfg: MessageMemberTimeoutConfig,
    *,
    http: HttpRequester | None = None,
    now: datetime | None = None,
) -> MessageMemberTimeoutResult:
    """Timeout a member.

    Raises:
        InvalidInputError, MissingConfigError, ExternalServiceError
    """
    _validate_request(req)
    _validate_config(cfg)

    base = cfg.api_base_url.rstrip("/")
    url = f"{base}/guilds/{req.guild_id}/members/{req.user_id}"

    current = now or datetime.now(timezone.utc)
    until = current + timedelta(seconds=req.duration_seconds)
    until_iso = _iso8601_utc(until)

    headers: dict[str, str] = {
        "Authorization": f"Bot {cfg.bot_token.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Thomas/MessageMemberTimeout",
    }
    if req.reason:
        # Discord expects this header to be URL-encoded.
        headers["X-Audit-Log-Reason"] = quote(req.reason, safe="")

    body = {"communication_disabled_until": until_iso}

    requester = http or _default_http_request
    try:
        resp = requester("PATCH", url, json=body, headers=headers, timeout=float(cfg.timeout_seconds))
    except MessageMemberTimeoutError:
        raise
    except Exception as exc:  # pragma: no cover
        raise ExternalServiceError(
            "External request failed.",
            details={"exception": type(exc).__name__},
        ) from exc

    status = getattr(resp, "status_code", None)
    if not isinstance(status, int):
        raise ExternalServiceError(
            "External service returned an invalid response.",
            details={"problem": "missing_status_code"},
        )

    if not (200 <= status < 300):
        details = {"status_code": status}
        details.update(_extract_error_details(resp))
        raise ExternalServiceError("External service request failed.", details=details)

    return MessageMemberTimeoutResult(
        guild_id=req.guild_id,
        user_id=req.user_id,
        duration_seconds=req.duration_seconds,
        timed_out_until=until_iso,
    )


def request_from_payload(payload: Mapping[str, Any]) -> MessageMemberTimeoutRequest:
    """Parse a request from a generic payload mapping.

    Accepted aliases:
    - server_id -> guild_id
    - member_id -> user_id
    - seconds -> duration_seconds
    """
    if not isinstance(payload, Mapping):
        raise InvalidInputError("Payload must be an object.")

    guild_id = payload.get("guild_id") or payload.get("server_id")
    user_id = payload.get("user_id") or payload.get("member_id")

    duration = payload.get("duration_seconds")
    if duration is None:
        duration = payload.get("seconds")

    normalized: MutableMapping[str, Any] = dict(payload)
    if guild_id is not None:
        normalized["guild_id"] = guild_id
    if user_id is not None:
        normalized["user_id"] = user_id
    if duration is not None:
        normalized["duration_seconds"] = duration

    guild_id_str = _require_str(normalized, "guild_id")
    user_id_str = _require_str(normalized, "user_id")
    duration_int = _require_int(normalized, "duration_seconds")

    reason = normalized.get("reason")
    message_id = normalized.get("message_id")

    # Keep these as-is if strings, otherwise stringify for traceability.
    reason_s = reason if (reason is None or isinstance(reason, str)) else str(reason)
    message_id_s = message_id if (message_id is None or isinstance(message_id, str)) else str(message_id)

    return MessageMemberTimeoutRequest(
        guild_id=guild_id_str,
        user_id=user_id_str,
        duration_seconds=duration_int,
        reason=reason_s,
        message_id=message_id_s,
    )


def config_from_mapping(config: Mapping[str, Any] | None) -> MessageMemberTimeoutConfig:
    """Load config from mapping, with env-var fallback."""
    cfg = dict(config or {})

    token = (
        cfg.get("bot_token")
        or cfg.get("discord_bot_token")
        or cfg.get("token")
        or os.getenv("THOMAS_DISCORD_BOT_TOKEN")
        or os.getenv("DISCORD_BOT_TOKEN")
    )

    api_base_url = cfg.get("api_base_url") or cfg.get("discord_api_base_url") or DEFAULT_API_BASE_URL

    timeout_val = cfg.get("timeout_seconds")
    if timeout_val is None:
        timeout_val = cfg.get("http_timeout_seconds")

    try:
        timeout_seconds = float(timeout_val) if timeout_val is not None else 10.0
    except (TypeError, ValueError):
        raise InvalidInputError("Field 'timeout_seconds' must be a positive number.", details={"field": "timeout_seconds"})

    return MessageMemberTimeoutConfig(
        bot_token=str(token) if token is not None else "",
        api_base_url=str(api_base_url),
        timeout_seconds=timeout_seconds,
    )


def run(
    payload: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None = None,
    http: HttpRequester | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute and return a machine-friendly envelope."""

    try:
        req = request_from_payload(payload)
        cfg = config_from_mapping(config)
        result = timeout_member(req, cfg, http=http, now=now)
        return {"ok": True, "result": result.to_dict()}
    except MessageMemberTimeoutError as exc:
        return {"ok": False, "error": exc.to_dict()}


# Stable exports / ergonomic aliases for other Thomas modules.
MemberTimeoutRequest = MessageMemberTimeoutRequest
MemberTimeoutConfig = MessageMemberTimeoutConfig
MemberTimeoutResult = MessageMemberTimeoutResult
parse_request = request_from_payload
parse_config = config_from_mapping
handle = run


__all__ = [
    "MessageMemberTimeoutError",
    "InvalidInputError",
    "MissingConfigError",
    "ExternalServiceError",
    "MessageMemberTimeoutRequest",
    "MessageMemberTimeoutConfig",
    "MessageMemberTimeoutResult",
    "MessageMemberTimeoutPayload",
    "MessageMemberTimeoutConfigDict",
    "timeout_member",
    "request_from_payload",
    "config_from_mapping",
    "run",
    "MemberTimeoutRequest",
    "MemberTimeoutConfig",
    "MemberTimeoutResult",
    "parse_request",
    "parse_config",
    "handle",
]
