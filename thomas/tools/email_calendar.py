"""Email and calendar tools (Gmail + Microsoft Graph).

This is the facade module that coordinates email and calendar operations.
Actual implementations are split into:
  - email_providers.py: Provider implementations (Gmail, Microsoft)
  - email_operations.py: EmailCalendarService and email operations
  - calendar_operations.py: Calendar-specific tool classes

Public API:
  - get_tools(): Return list of Tool instances for registration
  - load_email_calendar_config(): Load config from environ/thomas.toml
  - reset_email_calendar_service_for_tests(): For testing
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

try:
    import tomllib  # py3.11+
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore

try:
    from zoneinfo import ZoneInfo  # py3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

try:
    from thomas.tools.base import Tool, ToolError  # type: ignore
except ImportError:  # pragma: no cover

    class ToolError(RuntimeError):
        pass

    class Tool:
        name: str = ""
        description: str = ""
        params_schema: dict[str, Any] = {}

        async def run(self, ctx: Any = None, **params: Any) -> Any:
            raise NotImplementedError


# Import from submodules
from .calendar_operations import (  # noqa: E402
    CalendarCreateEventTool,
    CalendarSuggestTimesTool,
    CalendarTodayTool,
    CalendarWeekTool,
)
from .email_operations import _EmailCalendarService  # noqa: E402
from .email_providers import _GmailProvider, _MicrosoftProvider, _Provider  # noqa: E402

SETUP_DOC_HINT = "See docs/tools/email_calendar.md and configure [tools.email] in thomas.toml."


# ============================= CONFIG ==============================


@dataclass(frozen=True)
class EmailCalendarConfig:
    """Configuration for email/calendar tools."""

    provider: str  # "gmail" | "microsoft"
    client_id: str
    client_secret: str
    refresh_token: str
    tenant_id: str | None = None  # microsoft only

    timezone: str = "UTC"

    # Optional knobs that matter in real deployments
    http_timeout_s: float = 30.0
    max_connections: int = 20
    max_keepalive_connections: int = 10
    gmail_fetch_concurrency: int = 6

    # Microsoft delegated refresh tokens work best with explicit scopes.
    microsoft_scopes: list[str] | None = None


def _deep_get(d: dict[str, Any], keys: list[str]) -> Any | None:
    """Get nested dictionary value safely."""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _read_toml(path: str) -> dict[str, Any]:
    """Read TOML configuration file."""
    if tomllib is None:
        raise ToolError("tomllib is unavailable; use Python 3.11+ (or install tomli).")
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_email_calendar_config() -> EmailCalendarConfig:
    """Load email/calendar configuration from environment or thomas.toml."""
    env = os.environ.get
    toml_path = env("THOMAS_TOML") or "thomas.toml"

    cfg: dict[str, Any] = {}
    try:
        if os.path.exists(toml_path):
            cfg = _read_toml(toml_path)
    except (OSError, ValueError):
        cfg = {}

    provider = (
        (env("THOMAS_TOOLS_EMAIL_PROVIDER") or _deep_get(cfg, ["tools", "email", "provider"]) or "").strip().lower()
    )
    client_id = (env("THOMAS_TOOLS_EMAIL_CLIENT_ID") or _deep_get(cfg, ["tools", "email", "client_id"]) or "").strip()
    client_secret = (
        env("THOMAS_TOOLS_EMAIL_CLIENT_SECRET") or _deep_get(cfg, ["tools", "email", "client_secret"]) or ""
    ).strip()
    refresh_token = (
        env("THOMAS_TOOLS_EMAIL_REFRESH_TOKEN") or _deep_get(cfg, ["tools", "email", "refresh_token"]) or ""
    ).strip()
    tenant_id = env("THOMAS_TOOLS_EMAIL_TENANT_ID") or _deep_get(cfg, ["tools", "email", "tenant_id"]) or None
    tenant_id = str(tenant_id).strip() if tenant_id else None

    timezone_name = env("THOMAS_TOOLS_EMAIL_TIMEZONE") or _deep_get(cfg, ["tools", "email", "timezone"]) or "UTC"

    http_timeout_s = float(_deep_get(cfg, ["tools", "email", "http_timeout_s"]) or 30.0)
    max_connections = int(_deep_get(cfg, ["tools", "email", "max_connections"]) or 20)
    max_keepalive_connections = int(_deep_get(cfg, ["tools", "email", "max_keepalive_connections"]) or 10)
    gmail_fetch_concurrency = int(_deep_get(cfg, ["tools", "email", "gmail_fetch_concurrency"]) or 6)

    ms_scopes = _deep_get(cfg, ["tools", "email", "microsoft_scopes"])
    microsoft_scopes: list[str] | None = None
    if isinstance(ms_scopes, list):
        microsoft_scopes = [str(s).strip() for s in ms_scopes if str(s).strip()]

    return EmailCalendarConfig(
        provider=provider,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        tenant_id=tenant_id,
        timezone=str(timezone_name).strip() if timezone_name else "UTC",
        http_timeout_s=http_timeout_s,
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive_connections,
        gmail_fetch_concurrency=gmail_fetch_concurrency,
        microsoft_scopes=microsoft_scopes,
    )


def ensure_email_calendar_auth_configured(cfg: EmailCalendarConfig) -> None:
    """Validate that email/calendar credentials are configured."""
    missing: list[str] = []
    if cfg.provider not in {"gmail", "microsoft"}:
        missing.append("provider (gmail|microsoft)")
    if not cfg.client_id:
        missing.append("client_id")
    if not cfg.client_secret:
        missing.append("client_secret")
    if not cfg.refresh_token:
        missing.append("refresh_token")
    if cfg.provider == "microsoft" and not cfg.tenant_id:
        missing.append("tenant_id (microsoft only)")

    if missing:
        example = (
            "\n\nExample thomas.toml:\n"
            "[tools.email]\n"
            'provider = "gmail"  # or "microsoft"\n'
            'client_id = "..." \n'
            'client_secret = "..." \n'
            'refresh_token = "..." \n'
            '# tenant_id = "..."  # microsoft only\n'
            'timezone = "UTC"\n'
        )
        raise ToolError(
            "Email/Calendar credentials are not configured: " + ", ".join(missing) + ". " + SETUP_DOC_HINT + example
        )


# ========================= TIME HELPERS =========================


def _get_tz(tz_name: str) -> tzinfo:
    """Get tzinfo from timezone name."""
    if (tz_name or "").upper() == "UTC":
        return timezone.utc
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)  # type: ignore[return-value]
    except KeyError:
        return timezone.utc


def _start_end_for_day(d: date, tzinfo_: tzinfo) -> tuple[datetime, datetime]:
    """Get start and end datetime for a day."""
    start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tzinfo_)
    return start, start + timedelta(days=1)


def _now_iso_utc() -> str:
    """Get current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(s: str) -> datetime:
    """Parse ISO 8601 datetime string."""
    s = (s or "").strip()
    if not s:
        raise ToolError("Missing datetime value.")
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(s)
    except ValueError:
        raise ToolError(f"Invalid ISO datetime: {s!r}")


# ========================= HTTP HELPERS =========================


def _json_or_raise(resp: httpx.Response) -> dict[str, Any]:
    """Parse JSON response or raise ToolError."""
    try:
        data = resp.json()
    except ValueError:
        data = {"_raw": resp.text}

    if resp.status_code >= 400:
        msg = None
        if isinstance(data, dict):
            msg = data.get("error_description") or data.get("error")
            if isinstance(data.get("error"), dict):
                msg = msg or data["error"].get("message")
        msg = msg or f"HTTP {resp.status_code}: {resp.text[:500]}"
        raise ToolError(msg)

    if not isinstance(data, dict):
        raise ToolError("Unexpected API response (non-JSON object).")
    return data


def _parse_retry_after(headers: httpx.Headers) -> float | None:
    """Parse Retry-After header."""
    ra = headers.get("Retry-After")
    if not ra:
        return None
    ra = ra.strip()
    return float(ra) if ra.isdigit() else None


def _sleep_for_retry(attempt: int, retry_after_s: float | None = None) -> float:
    """Calculate sleep duration with exponential backoff and jitter."""
    base = min(10.0, 0.5 * (2**attempt))
    jitter = random.random() * 0.3
    return float(retry_after_s) if retry_after_s is not None else (base + jitter)


# ========================= TOKEN MANAGEMENT =========================


@dataclass
class _Token:
    """OAuth2 access token with expiration."""

    access_token: str
    expires_at_epoch: float

    def valid(self) -> bool:
        """Check if token is still valid."""
        return bool(self.access_token) and (time.time() < (self.expires_at_epoch - 60))


class _OAuthTokenManager:
    """Manages OAuth2 token refresh for Gmail and Microsoft Graph."""

    def __init__(self, cfg: EmailCalendarConfig) -> None:
        self.cfg = cfg
        self._tok: _Token | None = None
        self._lock = asyncio.Lock()

    async def get(self, http: httpx.AsyncClient, *, force_refresh: bool = False) -> str:
        """Get valid access token, refreshing if needed."""
        if not force_refresh and self._tok and self._tok.valid():
            return self._tok.access_token

        async with self._lock:
            if not force_refresh and self._tok and self._tok.valid():
                return self._tok.access_token

            if self.cfg.provider == "gmail":
                self._tok = await self._refresh_google(http)
            elif self.cfg.provider == "microsoft":
                self._tok = await self._refresh_microsoft(http)
            else:
                raise ToolError(f"Unsupported provider '{self.cfg.provider}'. {SETUP_DOC_HINT}")

            return self._tok.access_token

    async def _refresh_google(self, http: httpx.AsyncClient) -> _Token:
        """Refresh Google OAuth2 token."""
        resp = await http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.cfg.client_id,
                "client_secret": self.cfg.client_secret,
                "refresh_token": self.cfg.refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = _json_or_raise(resp)
        access = data.get("access_token") or ""
        expires_in = int(data.get("expires_in") or 3600)
        if not access:
            raise ToolError("Google token refresh failed (missing access_token). " + SETUP_DOC_HINT)
        return _Token(access_token=access, expires_at_epoch=time.time() + expires_in)

    async def _refresh_microsoft(self, http: httpx.AsyncClient) -> _Token:
        """Refresh Microsoft OAuth2 token."""
        tenant = self.cfg.tenant_id or "common"
        url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

        scopes = self.cfg.microsoft_scopes or [
            "offline_access",
            "Mail.Read",
            "Mail.Send",
            "Calendars.Read",
            "Calendars.ReadWrite",
        ]
        scope_str = " ".join(scopes)

        resp = await http.post(
            url,
            data={
                "client_id": self.cfg.client_id,
                "client_secret": self.cfg.client_secret,
                "refresh_token": self.cfg.refresh_token,
                "grant_type": "refresh_token",
                "scope": scope_str,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = _json_or_raise(resp)
        access = data.get("access_token") or ""
        expires_in = int(data.get("expires_in") or 3600)
        if not access:
            err = str(data.get("error") or "").lower()
            if "invalid_grant" in err:
                raise ToolError(
                    "Microsoft refresh_token is invalid/expired. Re-authorize and update refresh_token. "
                    + SETUP_DOC_HINT
                )
            raise ToolError("Microsoft token refresh failed (missing access_token). " + SETUP_DOC_HINT)
        return _Token(access_token=access, expires_at_epoch=time.time() + expires_in)


# ========================= SERVICE =============================

_SERVICE: _EmailCalendarService | None = None


def _get_service() -> _EmailCalendarService:
    """Get or create global email/calendar service."""
    global _SERVICE
    if _SERVICE is None:
        cfg = load_email_calendar_config()
        ensure_email_calendar_auth_configured(cfg)
        provider: _Provider
        if cfg.provider == "gmail":
            provider = _GmailProvider(_OAuthTokenManager(cfg))
        elif cfg.provider == "microsoft":
            provider = _MicrosoftProvider(_OAuthTokenManager(cfg))
        else:
            raise ToolError(f"Unsupported provider: {cfg.provider}")
        _SERVICE = _EmailCalendarService(provider, cfg)
    return _SERVICE


def reset_email_calendar_service_for_tests() -> None:
    """Reset service for testing."""
    global _SERVICE
    _SERVICE = None


# ========================= EMAIL TOOL CLASSES ======================


class EmailReadTool(Tool):
    """Tool to read recent email messages."""

    name = "email.read"
    description = "Read recent email messages (Gmail or Microsoft Graph)."
    params_schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            "filter": {
                "type": "string",
                "description": "Examples: 'unread', 'from:boss@company.com', 'subject:invoice'",
            },
            "folder": {"type": "string", "default": "inbox"},
        },
        "required": [],
        "additionalProperties": False,
    }

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        return await _get_service().email_read(
            count=int(params.get("count", 10)),
            filter=params.get("filter"),
            folder=str(params.get("folder", "inbox")),
        )


class EmailGetTool(Tool):
    """Tool to fetch a full email."""

    name = "email.get"
    description = "Fetch a full email (body + metadata)."
    params_schema = {
        "type": "object",
        "properties": {"message_id": {"type": "string"}},
        "required": ["message_id"],
        "additionalProperties": False,
    }

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        mid = str(params.get("message_id") or "").strip()
        if not mid:
            raise ToolError("email.get requires 'message_id'.")
        return await _get_service().email_get(message_id=mid)


class EmailSendTool(Tool):
    """Tool to send an email."""

    name = "email.send"
    description = "Send an email message."
    params_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "idempotency_key": {
                "type": "string",
                "description": "Stable key that makes retries return the first provider result without sending twice.",
            },
        },
        "required": ["to", "subject", "body"],
        "additionalProperties": False,
    }

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        to = str(params.get("to") or "").strip()
        if not to:
            raise ToolError("email.send requires 'to'.")
        return await _get_service().email_send(
            to=to,
            subject=str(params.get("subject") or "").strip(),
            body=str(params.get("body") or ""),
            idempotency_key=str(params.get("idempotency_key") or "").strip() or None,
        )


class EmailReplyTool(Tool):
    """Tool to reply to an email."""

    name = "email.reply"
    description = "Reply to an existing email thread."
    params_schema = {
        "type": "object",
        "properties": {"message_id": {"type": "string"}, "body": {"type": "string"}},
        "required": ["message_id", "body"],
        "additionalProperties": False,
    }

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        message_id = str(params.get("message_id") or "").strip()
        if not message_id:
            raise ToolError("email.reply requires 'message_id'.")
        return await _get_service().email_reply(message_id=message_id, body=str(params.get("body") or ""))


# ========================= TOOLS LIST ==========================

TOOLS: list[Tool] = [
    EmailReadTool(),
    EmailGetTool(),
    EmailSendTool(),
    EmailReplyTool(),
    CalendarTodayTool(),
    CalendarWeekTool(),
    CalendarCreateEventTool(),
    CalendarSuggestTimesTool(),
]


def get_tools() -> list[Tool]:
    """Return list of email/calendar tools for registration."""
    return TOOLS
