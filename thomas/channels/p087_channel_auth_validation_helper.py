"""
P087 - Channel auth validation helper (Thomas-native).

Purpose
-------
Provide a small, deterministic validation surface that can confirm whether a
messaging "channel" integration has usable authentication configured.

This module is designed to be:
- deterministic (stable error codes)
- safe for automation (machine-readable JSON via CLI wrapper)
- testable offline (HTTP call is factored for monkeypatching)

Supported channels (v1):
- telegram (alias: tg)

Notes
-----
This helper does *not* store tokens and does not log tokens. It only validates.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# =========================
# Contracts
# =========================


@dataclass(frozen=True, slots=True)
class ChannelAuthValidationRequest:
    """Input contract for a channel auth validation run."""

    channel: str
    token: str | None = None
    config: Mapping[str, Any] | None = None
    timeout_s: float = 10.0


@dataclass(frozen=True, slots=True)
class ChannelIdentity:
    """A minimal, channel-agnostic identity payload."""

    id: str
    username: str | None = None
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class ChannelAuthValidationResult:
    """Output contract for an auth validation run."""

    channel: str
    valid: bool
    identity: ChannelIdentity | None = None
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "valid": bool(self.valid),
            "identity": None
            if self.identity is None
            else {
                "id": self.identity.id,
                "username": self.identity.username,
                "display_name": self.identity.display_name,
            },
            "details": dict(self.details or {}),
        }


# =========================
# Deterministic errors
# =========================


class ChannelAuthValidationError(Exception):
    """Base class for deterministic failures."""

    code: str = "CHANNEL_AUTH_VALIDATION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        channel: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.channel = channel
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "channel": self.channel,
            "details": dict(self.details or {}),
        }


class InvalidChannelAuthInputError(ChannelAuthValidationError):
    code = "INVALID_INPUT"


class MissingChannelAuthConfigError(ChannelAuthValidationError):
    code = "MISSING_CONFIG"


class ExternalChannelAuthValidationError(ChannelAuthValidationError):
    code = "EXTERNAL_FAILURE"


# =========================
# Public API
# =========================


_SUPPORTED_CHANNELS: dict[str, str] = {
    "telegram": "telegram",
    "tg": "telegram",
}


def validate_channel_auth(request: ChannelAuthValidationRequest) -> ChannelAuthValidationResult:
    """Validate authentication for the requested channel."""

    if not isinstance(request, ChannelAuthValidationRequest):
        raise InvalidChannelAuthInputError(
            "request must be a ChannelAuthValidationRequest",
            details={"received_type": type(request).__name__},
        )

    channel_raw = (request.channel or "").strip().lower()
    if not channel_raw:
        raise InvalidChannelAuthInputError("channel is required")

    channel = _SUPPORTED_CHANNELS.get(channel_raw)
    if channel is None:
        raise InvalidChannelAuthInputError(
            f"unsupported channel: {request.channel!r}",
            channel=channel_raw,
            details={"supported": sorted(set(_SUPPORTED_CHANNELS.values()))},
        )

    if not isinstance(request.timeout_s, (int, float)) or float(request.timeout_s) <= 0:
        raise InvalidChannelAuthInputError(
            "timeout_s must be a positive number",
            channel=channel,
            details={"timeout_s": request.timeout_s},
        )

    token = _resolve_token(channel=channel, token_override=request.token, config=request.config)
    token_source = _token_source(channel=channel, token_override=request.token, config=request.config)

    if channel == "telegram":
        ident = _validate_telegram(token=token, timeout_s=float(request.timeout_s))
        return ChannelAuthValidationResult(
            channel=channel,
            valid=True,
            identity=ident,
            details={"source": token_source},
        )

    # defensive (should be unreachable)
    raise InvalidChannelAuthInputError(f"unsupported channel: {channel!r}", channel=channel)


# =========================
# Token resolution
# =========================


def _token_source(*, channel: str, token_override: str | None, config: Mapping[str, Any] | None) -> str:
    if token_override and token_override.strip():
        return "override"
    if _token_from_config(channel, config):
        return "config"
    if _token_from_env(channel):
        return "env"
    return "unknown"


def _resolve_token(*, channel: str, token_override: str | None, config: Mapping[str, Any] | None) -> str:
    tok = (token_override or "").strip()
    if tok:
        return tok

    tok = (_token_from_config(channel, config) or "").strip()
    if tok:
        return tok

    tok = (_token_from_env(channel) or "").strip()
    if tok:
        return tok

    raise MissingChannelAuthConfigError(
        f"missing authentication credentials for channel '{channel}'",
        channel=channel,
        details={"expected_env_vars": _expected_env_vars(channel)},
    )


def _token_from_config(channel: str, config: Mapping[str, Any] | None) -> str | None:
    """Try multiple common config shapes without binding to a specific config system."""

    if not config or not isinstance(config, Mapping):
        return None

    def get_str(m: Mapping[str, Any], k: str) -> str | None:
        v = m.get(k)
        if v is None:
            return None
        return v if isinstance(v, str) else str(v)

    candidates: list[str | None] = []

    # flat keys
    candidates.extend([get_str(config, "token"), get_str(config, "bot_token"), get_str(config, "api_token")])

    # nested: config["channels"][channel]
    channels_cfg = config.get("channels")
    if isinstance(channels_cfg, Mapping):
        chan_cfg = channels_cfg.get(channel)
        if isinstance(chan_cfg, Mapping):
            candidates.extend(
                [get_str(chan_cfg, "token"), get_str(chan_cfg, "bot_token"), get_str(chan_cfg, "api_token")]
            )

    # nested: config[channel]
    chan_cfg2 = config.get(channel)
    if isinstance(chan_cfg2, Mapping):
        candidates.extend(
            [get_str(chan_cfg2, "token"), get_str(chan_cfg2, "bot_token"), get_str(chan_cfg2, "api_token")]
        )

    for c in candidates:
        if c and c.strip():
            return c
    return None


def _expected_env_vars(channel: str) -> list[str]:
    c = channel.upper()
    vars_ = [
        f"THOMAS_{c}_TOKEN",
        f"THOMAS_{c}_BOT_TOKEN",
        f"{c}_TOKEN",
        f"{c}_BOT_TOKEN",
    ]
    if channel == "telegram":
        vars_.extend(
            [
                "TELEGRAM_TOKEN",
                "TELEGRAM_BOT_TOKEN",
                "THOMAS_TELEGRAM_TOKEN",
                "THOMAS_TELEGRAM_BOT_TOKEN",
            ]
        )

    # dedupe while preserving order
    out: list[str] = []
    for v in vars_:
        if v not in out:
            out.append(v)
    return out


def _token_from_env(channel: str) -> str | None:
    for key in _expected_env_vars(channel):
        v = os.getenv(key)
        if v and v.strip():
            return v
    return None


# =========================
# Telegram validation
# =========================


def _validate_telegram(*, token: str, timeout_s: float) -> ChannelIdentity:
    """Validate a Telegram bot token."""

    ident = _try_validate_telegram_via_integration(token=token, timeout_s=timeout_s)
    if ident is not None:
        return ident

    return _validate_telegram_via_http(token=token, timeout_s=timeout_s)


def _try_validate_telegram_via_integration(*, token: str, timeout_s: float) -> ChannelIdentity | None:
    """Best-effort shim over thomas.integrations.telegram."""

    try:
        import importlib

        mod = importlib.import_module("thomas.integrations.telegram")
    except (ImportError, AttributeError, RuntimeError):
        return None

    for fn_name in ("get_me", "getMe", "whoami", "bot_info", "validate_token", "validate_bot_token"):
        fn = getattr(mod, fn_name, None)
        if not callable(fn):
            continue

        try:
            try:
                res = fn(token, timeout_s=timeout_s)  # type: ignore[misc]
            except TypeError:
                res = fn(token)  # type: ignore[misc]
        except (ImportError, AttributeError, RuntimeError) as e:
            raise ExternalChannelAuthValidationError(
                "telegram auth validation failed",
                channel="telegram",
                details={"source": "integration", "call": fn_name, "exc_type": type(e).__name__},
            ) from e

        parsed = _parse_telegram_identity(res)
        if parsed is not None:
            return parsed

        if isinstance(res, bool):
            if res:
                return ChannelIdentity(id="unknown")
            raise ExternalChannelAuthValidationError(
                "telegram auth rejected by integration",
                channel="telegram",
                details={"source": "integration", "call": fn_name},
            )

        # unknown payload -> fall back to HTTP
        return None

    return None


def _validate_telegram_via_http(*, token: str, timeout_s: float) -> ChannelIdentity:
    """Minimal HTTPS call to Telegram Bot API getMe."""

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        payload = _http_get_json(url=url, timeout_s=timeout_s)
    except ExternalChannelAuthValidationError:
        raise
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise ExternalChannelAuthValidationError(
            "telegram auth validation failed",
            channel="telegram",
            details={"source": "http", "exc_type": type(e).__name__},
        ) from e

    if isinstance(payload, Mapping) and payload.get("ok") is False:
        raise ExternalChannelAuthValidationError(
            "telegram API rejected credentials",
            channel="telegram",
            details={
                "source": "http",
                "error_code": payload.get("error_code"),
                "description": payload.get("description"),
            },
        )

    parsed = _parse_telegram_identity(payload)
    if parsed is None:
        raise ExternalChannelAuthValidationError(
            "telegram auth validation returned unrecognized payload",
            channel="telegram",
            details={"source": "http"},
        )

    return parsed


def _http_get_json(*, url: str, timeout_s: float) -> Any:
    """Fetch JSON from URL (GET). Separated for test monkeypatching."""

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        body = None
        try:
            body = e.read()
        except (json.JSONDecodeError, ValueError, KeyError):
            body = None
        raise ExternalChannelAuthValidationError(
            "HTTP request returned error status",
            channel="telegram",
            details={
                "source": "http",
                "status_code": getattr(e, "code", None),
                "body": _safe_body_snippet(body),
            },
        ) from e
    except (ImportError, AttributeError, RuntimeError) as e:
        raise ExternalChannelAuthValidationError(
            "HTTP request failed",
            channel="telegram",
            details={"source": "http", "exc_type": type(e).__name__},
        ) from e

    try:
        return json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise ExternalChannelAuthValidationError(
            "HTTP response was not valid JSON",
            channel="telegram",
            details={"source": "http", "exc_type": type(e).__name__},
        ) from e


def _safe_body_snippet(body: Any, *, max_len: int = 200) -> str | None:
    if body is None:
        return None
    if isinstance(body, (bytes, bytearray)):
        try:
            s = body.decode("utf-8", errors="replace")
        except (json.JSONDecodeError, ValueError, KeyError):
            s = repr(body)
    else:
        s = str(body)
    s = s.strip().replace("\n", " ").replace("\r", " ")
    return s[:max_len] if s else None


def _parse_telegram_identity(payload: Any) -> ChannelIdentity | None:
    """Normalize plausible Telegram getMe payload shapes into ChannelIdentity."""

    if payload is None:
        return None

    # Telegram envelope
    if isinstance(payload, Mapping) and "ok" in payload and "result" in payload:
        return _parse_telegram_identity(payload.get("result"))

    if isinstance(payload, Mapping):
        if "id" in payload:
            bot_id = str(payload.get("id"))
            username = payload.get("username")
            first_name = payload.get("first_name") or payload.get("name")
            display_name = str(first_name) if first_name is not None else None
            return ChannelIdentity(
                id=bot_id,
                username=str(username) if username is not None else None,
                display_name=display_name,
            )

    # object payload
    bot_id = getattr(payload, "id", None)
    if bot_id is not None:
        username = getattr(payload, "username", None)
        display_name = getattr(payload, "first_name", None) or getattr(payload, "name", None)
        return ChannelIdentity(
            id=str(bot_id),
            username=str(username) if username is not None else None,
            display_name=str(display_name) if display_name is not None else None,
        )

    return None
