"""
P067 - Message role assign and remove (Thomas-native).

Provides deterministic functions to assign/remove a Discord role for a guild member.
No Reference CLI naming is reused.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

_DISCORD_API_BASE = "https://discord.com/api/v10"
RoleChangeAction = Literal["assign", "remove"]


class MessageRoleError(RuntimeError):
    """Deterministic, machine-readable error for role operations."""

    code: str
    details: dict[str, Any]

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class InvalidMessageRoleInput(MessageRoleError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__("invalid_input", message, details=details)


class MissingMessageRoleConfig(MessageRoleError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__("missing_config", message, details=details)


class ExternalMessageRoleFailure(MessageRoleError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__("external_failure", message, details=details)


@dataclass(frozen=True)
class MessageRoleChangeRequest:
    guild_id: str
    user_id: str
    role_id: str
    action: RoleChangeAction
    discord_bot_token: str | None = None
    timeout_s: float = 15.0


@dataclass(frozen=True)
class MessageRoleChangeResult:
    ok: bool
    action: RoleChangeAction
    guild_id: str
    user_id: str
    role_id: str
    provider: str = "discord"
    status_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "action": self.action,
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "role_id": self.role_id,
            "status_code": self.status_code,
        }


_ID_RE = re.compile(r"^[0-9]{1,25}$")


def _validate_discord_id(name: str, value: str) -> None:
    if not value or not isinstance(value, str):
        raise InvalidMessageRoleInput(f"{name} is required", details={"field": name})
    if not _ID_RE.match(value):
        raise InvalidMessageRoleInput(
            f"{name} must be a numeric Discord snowflake id",
            details={"field": name, "value": value},
        )


def _discord_role_endpoint(guild_id: str, user_id: str, role_id: str) -> str:
    return f"{_DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}/roles/{role_id}"


def _dig_for_token(cfg: Any) -> str | None:
    candidate_keys = {"discord_bot_token", "bot_token", "token", "discord_token"}

    if isinstance(cfg, dict):
        for k in candidate_keys:
            v = cfg.get(k)
            if isinstance(v, str) and v:
                return v
        for nested_key in ("discord", "channels", "messaging"):
            nested = cfg.get(nested_key)
            if nested is None:
                continue
            tok = _dig_for_token(nested)
            if tok:
                return tok
        return None

    for attr in ("discord_bot_token", "bot_token", "token", "discord_token"):
        v = getattr(cfg, attr, None)
        if isinstance(v, str) and v:
            return v

    for attr in ("discord", "channels", "messaging"):
        nested = getattr(cfg, attr, None)
        if nested is None:
            continue
        tok = _dig_for_token(nested)
        if tok:
            return tok

    return None


def _resolve_discord_bot_token(explicit: str | None) -> str:
    if explicit:
        return explicit

    for key in (
        "THOMAS_DISCORD_BOT_TOKEN",
        "THOMAS_DISCORD_TOKEN",
        "DISCORD_BOT_TOKEN",
        "DISCORD_TOKEN",
    ):
        token = os.getenv(key)
        if token:
            return token

    # Best-effort Thomas config lookup if available (no hard dependency).
    try:
        from thomas.config import load_config  # type: ignore
    except ImportError:
        load_config = None  # type: ignore

    if load_config is not None:
        try:
            cfg = load_config()
            tok = _dig_for_token(cfg)
            if tok:
                return tok
        except Exception:
            pass

    raise MissingMessageRoleConfig(
        "Discord bot token is not configured",
        details={
            "expected_env": [
                "THOMAS_DISCORD_BOT_TOKEN",
                "THOMAS_DISCORD_TOKEN",
                "DISCORD_BOT_TOKEN",
                "DISCORD_TOKEN",
            ]
        },
    )


@dataclass(frozen=True)
class HttpResult:
    status_code: int
    headers: dict[str, str]
    body: bytes


HttpRequestFn = Callable[[str, str, dict[str, str], float], HttpResult]


def _default_http_request(method: str, url: str, headers: dict[str, str], timeout_s: float) -> HttpResult:
    req = urllib.request.Request(url=url, method=method)
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read() or b""
            hdrs = {k.lower(): v for k, v in dict(resp.headers).items()}
            return HttpResult(status_code=int(resp.status), headers=hdrs, body=body)
    except urllib.error.HTTPError as e:
        body = e.read() or b""
        hdrs = {k.lower(): v for k, v in dict(getattr(e, "headers", {}) or {}).items()}
        return HttpResult(status_code=int(e.code), headers=hdrs, body=body)
    except urllib.error.URLError as e:
        raise ExternalMessageRoleFailure(
            "Discord request failed",
            details={"error": str(e), "url": url, "method": method},
        ) from e


def _parse_body(result: HttpResult) -> tuple[Any | None, str]:
    body_text = ""
    body_json: Any | None = None
    if result.body:
        try:
            body_text = result.body.decode("utf-8", errors="replace")
        except (json.JSONDecodeError, ValueError, KeyError):
            body_text = ""
        # Try JSON decode if it looks like JSON or content-type says json.
        ctype = (result.headers.get("content-type") or "").lower()
        if "application/json" in ctype or (body_text and body_text.lstrip().startswith(("{", "["))):
            try:
                body_json = json.loads(body_text)
            except (json.JSONDecodeError, ValueError, KeyError):
                body_json = None
    return body_json, body_text


def change_member_role(
    request: MessageRoleChangeRequest,
    *,
    http_request: HttpRequestFn | None = None,
) -> MessageRoleChangeResult:
    """
    Assign or remove a role for a member in a Discord guild.

    Raises:
        InvalidMessageRoleInput
        MissingMessageRoleConfig
        ExternalMessageRoleFailure
    """
    _validate_discord_id("guild_id", request.guild_id)
    _validate_discord_id("user_id", request.user_id)
    _validate_discord_id("role_id", request.role_id)

    if request.action not in ("assign", "remove"):
        raise InvalidMessageRoleInput(
            "action must be 'assign' or 'remove'",
            details={"field": "action", "value": request.action},
        )

    token = _resolve_discord_bot_token(request.discord_bot_token)
    method = "PUT" if request.action == "assign" else "DELETE"
    url = _discord_role_endpoint(request.guild_id, request.user_id, request.role_id)

    headers = {
        "authorization": f"Bot {token}",
        "user-agent": "thomas/role-manager (P067)",
    }

    http_request = http_request or _default_http_request
    result = http_request(method, url, headers, request.timeout_s)

    if result.status_code == 204:
        return MessageRoleChangeResult(
            ok=True,
            action=request.action,
            guild_id=request.guild_id,
            user_id=request.user_id,
            role_id=request.role_id,
            status_code=result.status_code,
        )

    body_json, body_text = _parse_body(result)

    details: dict[str, Any] = {
        "status_code": result.status_code,
        "action": request.action,
        "guild_id": request.guild_id,
        "user_id": request.user_id,
        "role_id": request.role_id,
    }

    # Helpful rate-limit surface (Discord uses 429).
    if result.status_code == 429:
        if "retry-after" in result.headers:
            details["retry_after_s"] = result.headers.get("retry-after")
        if "x-ratelimit-reset-after" in result.headers:
            details["ratelimit_reset_after_s"] = result.headers.get("x-ratelimit-reset-after")
        if "x-ratelimit-bucket" in result.headers:
            details["ratelimit_bucket"] = result.headers.get("x-ratelimit-bucket")

    if body_json is not None:
        details["response_json"] = body_json
    elif body_text:
        details["response_text"] = body_text[:500]

    raise ExternalMessageRoleFailure("Discord rejected the role change request", details=details)


def assign_role_to_member(
    *,
    guild_id: str,
    user_id: str,
    role_id: str,
    discord_bot_token: str | None = None,
    timeout_s: float = 15.0,
    http_request: HttpRequestFn | None = None,
) -> MessageRoleChangeResult:
    return change_member_role(
        MessageRoleChangeRequest(
            guild_id=guild_id,
            user_id=user_id,
            role_id=role_id,
            action="assign",
            discord_bot_token=discord_bot_token,
            timeout_s=timeout_s,
        ),
        http_request=http_request,
    )


def remove_role_from_member(
    *,
    guild_id: str,
    user_id: str,
    role_id: str,
    discord_bot_token: str | None = None,
    timeout_s: float = 15.0,
    http_request: HttpRequestFn | None = None,
) -> MessageRoleChangeResult:
    return change_member_role(
        MessageRoleChangeRequest(
            guild_id=guild_id,
            user_id=user_id,
            role_id=role_id,
            action="remove",
            discord_bot_token=discord_bot_token,
            timeout_s=timeout_s,
        ),
        http_request=http_request,
    )
