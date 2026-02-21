# thomas/tools/email_calendar.py
from __future__ import annotations

import asyncio
import base64
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple

import httpx

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


# ---------------------------------------------------------------------------
# Thomas tool base compatibility
# ---------------------------------------------------------------------------

try:
    from thomas.tools.base import Tool, ToolError  # type: ignore
except Exception:  # pragma: no cover
    class ToolError(RuntimeError):
        pass

    class Tool:
        name: str = ""
        description: str = ""
        params_schema: Dict[str, Any] = {}

        async def run(self, ctx: Any = None, **params: Any) -> Any:
            raise NotImplementedError


SETUP_DOC_HINT = "See docs/tools/email_calendar.md and configure [tools.email] in thomas.toml."


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EmailCalendarConfig:
    provider: str  # "gmail" | "microsoft"
    client_id: str
    client_secret: str
    refresh_token: str
    tenant_id: Optional[str] = None  # microsoft only

    timezone: str = "UTC"

    # Optional knobs that matter in real deployments
    http_timeout_s: float = 30.0
    max_connections: int = 20
    max_keepalive_connections: int = 10
    gmail_fetch_concurrency: int = 6

    # Microsoft delegated refresh tokens work best with explicit scopes.
    # If you're using application permissions + .default, change microsoft refresh flow accordingly.
    microsoft_scopes: Optional[List[str]] = None


def _deep_get(d: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _read_toml(path: str) -> Dict[str, Any]:
    if tomllib is None:
        raise ToolError("tomllib is unavailable; use Python 3.11+ (or install tomli).")
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_email_calendar_config() -> EmailCalendarConfig:
    env = os.environ.get
    toml_path = env("THOMAS_TOML") or "thomas.toml"

    cfg: Dict[str, Any] = {}
    try:
        if os.path.exists(toml_path):
            cfg = _read_toml(toml_path)
    except Exception:
        cfg = {}

    provider = (env("THOMAS_TOOLS_EMAIL_PROVIDER") or _deep_get(cfg, ["tools", "email", "provider"]) or "").strip().lower()
    client_id = (env("THOMAS_TOOLS_EMAIL_CLIENT_ID") or _deep_get(cfg, ["tools", "email", "client_id"]) or "").strip()
    client_secret = (env("THOMAS_TOOLS_EMAIL_CLIENT_SECRET") or _deep_get(cfg, ["tools", "email", "client_secret"]) or "").strip()
    refresh_token = (env("THOMAS_TOOLS_EMAIL_REFRESH_TOKEN") or _deep_get(cfg, ["tools", "email", "refresh_token"]) or "").strip()
    tenant_id = (env("THOMAS_TOOLS_EMAIL_TENANT_ID") or _deep_get(cfg, ["tools", "email", "tenant_id"]) or None)
    tenant_id = str(tenant_id).strip() if tenant_id else None

    timezone_name = (env("THOMAS_TOOLS_EMAIL_TIMEZONE") or _deep_get(cfg, ["tools", "email", "timezone"]) or "UTC")

    http_timeout_s = float(_deep_get(cfg, ["tools", "email", "http_timeout_s"]) or 30.0)
    max_connections = int(_deep_get(cfg, ["tools", "email", "max_connections"]) or 20)
    max_keepalive_connections = int(_deep_get(cfg, ["tools", "email", "max_keepalive_connections"]) or 10)
    gmail_fetch_concurrency = int(_deep_get(cfg, ["tools", "email", "gmail_fetch_concurrency"]) or 6)

    ms_scopes = _deep_get(cfg, ["tools", "email", "microsoft_scopes"])
    microsoft_scopes: Optional[List[str]] = None
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
    """
    Auth helper required by spec.
    Raises ToolError with clear setup guidance (no secret leakage).
    """
    missing: List[str] = []
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
            "Email/Calendar credentials are not configured: "
            + ", ".join(missing)
            + ". "
            + SETUP_DOC_HINT
            + example
        )


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _get_tz(tz_name: str) -> tzinfo:
    if (tz_name or "").upper() == "UTC":
        return timezone.utc
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)  # type: ignore[return-value]
    except Exception:
        return timezone.utc


def _start_end_for_day(d: date, tzinfo_: tzinfo) -> Tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tzinfo_)
    return start, start + timedelta(days=1)


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(s: str) -> datetime:
    s = (s or "").strip()
    if not s:
        raise ToolError("Missing datetime value.")
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(s)
    except Exception:
        raise ToolError(f"Invalid ISO datetime: {s!r}")


# ---------------------------------------------------------------------------
# HTTP + retry helpers
# ---------------------------------------------------------------------------

def _json_or_raise(resp: httpx.Response) -> Dict[str, Any]:
    try:
        data = resp.json()
    except Exception:
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


def _parse_retry_after(headers: httpx.Headers) -> Optional[float]:
    ra = headers.get("Retry-After")
    if not ra:
        return None
    ra = ra.strip()
    return float(ra) if ra.isdigit() else None


def _sleep_for_retry(attempt: int, retry_after_s: Optional[float] = None) -> float:
    base = min(10.0, 0.5 * (2 ** attempt))
    jitter = random.random() * 0.3
    return float(retry_after_s) if retry_after_s is not None else (base + jitter)


# ---------------------------------------------------------------------------
# OAuth token management
# ---------------------------------------------------------------------------

@dataclass
class _Token:
    access_token: str
    expires_at_epoch: float

    def valid(self) -> bool:
        return bool(self.access_token) and (time.time() < (self.expires_at_epoch - 60))


class _OAuthTokenManager:
    def __init__(self, cfg: EmailCalendarConfig) -> None:
        self.cfg = cfg
        self._tok: Optional[_Token] = None
        self._lock = asyncio.Lock()

    async def get(self, http: httpx.AsyncClient, *, force_refresh: bool = False) -> str:
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
                raise ToolError("Microsoft refresh_token is invalid/expired. Re-authorize and update refresh_token. " + SETUP_DOC_HINT)
            raise ToolError("Microsoft token refresh failed (missing access_token). " + SETUP_DOC_HINT)
        return _Token(access_token=access, expires_at_epoch=time.time() + expires_in)


# ---------------------------------------------------------------------------
# Shaping helpers
# ---------------------------------------------------------------------------

def _fold_csv(s: str) -> str:
    return ", ".join([p.strip() for p in (s or "").split(",") if p.strip()])


def _split_csv(s: str) -> List[str]:
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _preview_200(s: str) -> str:
    return (s or "")[:200]


def _safe_int(x: Any, default: int) -> int:
    try:
        return int(x)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class _Provider:
    async def email_read(self, count: int, filter: Optional[str], folder: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    async def email_get(self, message_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def email_send(self, to: str, subject: str, body: str, cc: Optional[str], body_type: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def email_reply(self, message_id: str, body: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def calendar_list(self, time_min: datetime, time_max: datetime) -> List[Dict[str, Any]]:
        raise NotImplementedError

    async def calendar_create_event(
        self, title: str, start: str, end: str, attendees: List[str], location: str, body: str
    ) -> Dict[str, Any]:
        raise NotImplementedError

    # Optional best-effort: free/busy for attendees (works best inside orgs / shared calendars)
    async def calendar_freebusy(self, time_min: datetime, time_max: datetime, attendees: List[str]) -> Dict[str, Any]:
        return {"note": "freebusy not supported for this provider/config", "busy": []}


# ---------------------------------------------------------------------------
# Gmail provider
# ---------------------------------------------------------------------------

class _GmailProvider(_Provider):
    def __init__(self, cfg: EmailCalendarConfig, http: httpx.AsyncClient) -> None:
        self.cfg = cfg
        self.http = http
        self.tokens = _OAuthTokenManager(cfg)
        self._sem = asyncio.Semaphore(max(1, int(cfg.gmail_fetch_concurrency)))

    async def _headers(self, *, force_refresh: bool = False) -> Dict[str, str]:
        tok = await self.tokens.get(self.http, force_refresh=force_refresh)
        return {"Authorization": f"Bearer {tok}"}

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        refreshed = False
        for attempt in range(5):
            try:
                resp = await self.http.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    data=data,
                    headers=await self._headers(force_refresh=False),
                )
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt >= 4:
                    raise ToolError("Network error talking to Gmail/Google APIs.")
                await asyncio.sleep(_sleep_for_retry(attempt))
                continue

            if resp.status_code == 401 and not refreshed:
                _ = await self.tokens.get(self.http, force_refresh=True)
                refreshed = True
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt >= 4:
                    _ = _json_or_raise(resp)
                await asyncio.sleep(_sleep_for_retry(attempt, _parse_retry_after(resp.headers)))
                continue

            return _json_or_raise(resp)

        raise ToolError("Gmail request failed after retries.")

    def _gmail_query(self, filter: Optional[str], folder: str) -> Optional[str]:
        parts: List[str] = []
        fldr = (folder or "inbox").strip().lower()
        if fldr and fldr not in {"all", "allmail", "all_mail"}:
            parts.append(f"in:{fldr}")
        if filter:
            f = filter.strip()
            if f:
                parts.append("is:unread" if f.lower() == "unread" else f)
        q = " ".join(parts).strip()
        return q or None

    async def email_read(self, count: int, filter: Optional[str], folder: str) -> List[Dict[str, Any]]:
        count = max(1, min(int(count), 50))
        q = self._gmail_query(filter, folder)

        lst = await self._request_json(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params={"maxResults": count, **({"q": q} if q else {})},
        )
        ids = [m.get("id") for m in (lst.get("messages") or []) if m.get("id")][:count]
        if not ids:
            return []

        fields = (
            "id,threadId,internalDate,snippet,labelIds,"
            "payload(headers,name,value,parts,filename,body/attachmentId)"
        )

        async def fetch(mid: str) -> Dict[str, Any]:
            async with self._sem:
                data = await self._request_json(
                    "GET",
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
                    params={"format": "full", "fields": fields},
                )
                payload = data.get("payload") or {}
                headers = {h.get("name", "").lower(): h.get("value", "") for h in (payload.get("headers") or [])}
                received = _try_rfc2822_to_iso(headers.get("date", "") or "") or _try_internal_ms_to_iso(data.get("internalDate")) or ""

                label_ids = data.get("labelIds") or []
                is_unread = "UNREAD" in set(label_ids)

                return {
                    "id": data.get("id") or mid,
                    "thread_id": data.get("threadId") or "",
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "subject": headers.get("subject", ""),
                    "preview": _preview_200(data.get("snippet") or ""),
                    "received_at": received,
                    "has_attachments": bool(_gmail_has_attachments(payload)),
                    "is_unread": is_unread,
                    "labels": label_ids,
                }

        return list(await asyncio.gather(*[fetch(mid) for mid in ids], return_exceptions=False))

    async def email_get(self, message_id: str) -> Dict[str, Any]:
        if not message_id:
            raise ToolError("email.get requires 'message_id'.")

        data = await self._request_json(
            "GET",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            params={"format": "full"},
        )

        payload = data.get("payload") or {}
        headers = {h.get("name", "").lower(): h.get("value", "") for h in (payload.get("headers") or [])}
        received = _try_rfc2822_to_iso(headers.get("date", "") or "") or _try_internal_ms_to_iso(data.get("internalDate")) or ""
        label_ids = data.get("labelIds") or []
        is_unread = "UNREAD" in set(label_ids)

        text_body, html_body, attachments = _gmail_extract_bodies_and_attachments(payload)

        return {
            "id": data.get("id") or message_id,
            "thread_id": data.get("threadId") or "",
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "received_at": received,
            "is_unread": is_unread,
            "labels": label_ids,
            "body_text": text_body,
            "body_html": html_body,
            "attachments": attachments,
        }

    async def email_send(self, to: str, subject: str, body: str, cc: Optional[str], body_type: str) -> Dict[str, Any]:
        to = _fold_csv(to)
        if not to:
            raise ToolError("email.send requires a non-empty 'to'.")

        msg = EmailMessage()
        msg["To"] = to
        if cc:
            msg["Cc"] = _fold_csv(cc)
        msg["Subject"] = subject or ""

        subtype = "html" if (body_type or "text").lower() == "html" else "plain"
        msg.set_content(body or "", subtype=subtype)

        raw = _b64url(msg.as_bytes())
        out = await self._request_json(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json_body={"raw": raw},
        )
        return {"message_id": out.get("id") or "", "sent_at": _now_iso_utc()}

    async def email_reply(self, message_id: str, body: str) -> Dict[str, Any]:
        if not message_id:
            raise ToolError("email.reply requires 'message_id'.")

        orig = await self._request_json(
            "GET",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            params={
                "format": "metadata",
                "metadataHeaders": ["From", "Subject", "Message-ID", "References", "Reply-To"],
            },
        )
        payload = orig.get("payload") or {}
        headers = {h.get("name", "").lower(): h.get("value", "") for h in (payload.get("headers") or [])}

        thread_id = orig.get("threadId") or ""
        subject = headers.get("subject", "") or ""
        if subject and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        reply_to = headers.get("reply-to") or headers.get("from") or ""
        orig_msgid = headers.get("message-id", "") or ""
        references = (headers.get("references", "") or "").strip()

        msg = EmailMessage()
        msg["To"] = reply_to
        msg["Subject"] = subject
        if orig_msgid:
            msg["In-Reply-To"] = orig_msgid
            msg["References"] = (references + " " + orig_msgid).strip() if references else orig_msgid
        elif references:
            msg["References"] = references

        msg.set_content(body or "", subtype="plain")
        raw = _b64url(msg.as_bytes())

        payload_out: Dict[str, Any] = {"raw": raw}
        if thread_id:
            payload_out["threadId"] = thread_id

        out = await self._request_json(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json_body=payload_out,
        )
        return {"message_id": out.get("id") or "", "sent_at": _now_iso_utc()}

    async def calendar_list(self, time_min: datetime, time_max: datetime) -> List[Dict[str, Any]]:
        params = {
            "timeMin": time_min.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "timeMax": time_max.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        data = await self._request_json(
            "GET",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params=params,
        )
        return [_google_event_to_common(ev) for ev in (data.get("items") or [])]

    async def calendar_freebusy(self, time_min: datetime, time_max: datetime, attendees: List[str]) -> Dict[str, Any]:
        items = [{"id": "primary"}]
        for a in attendees:
            a = (a or "").strip()
            if a:
                items.append({"id": a})

        body = {
            "timeMin": time_min.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "timeMax": time_max.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "items": items,
        }
        data = await self._request_json(
            "POST",
            "https://www.googleapis.com/calendar/v3/freeBusy",
            json_body=body,
        )
        return data

    async def calendar_create_event(
        self, title: str, start: str, end: str, attendees: List[str], location: str, body: str
    ) -> Dict[str, Any]:
        start_dt = _parse_iso_datetime(start)
        end_dt = _parse_iso_datetime(end)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        event: Dict[str, Any] = {
            "summary": title,
            "location": location or "",
            "description": body or "",
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
        }
        if attendees:
            event["attendees"] = [{"email": a} for a in attendees if a]

        out = await self._request_json(
            "POST",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            json_body=event,
        )
        return _google_event_to_common(out)


def _try_rfc2822_to_iso(s: str) -> Optional[str]:
    try:
        from email.utils import parsedate_to_datetime  # type: ignore
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _try_internal_ms_to_iso(ms: Any) -> Optional[str]:
    try:
        v = int(ms)
        return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _gmail_has_attachments(payload: Dict[str, Any]) -> bool:
    def walk(part: Dict[str, Any]) -> bool:
        if not isinstance(part, dict):
            return False
        if part.get("filename"):
            return True
        body = part.get("body") or {}
        if isinstance(body, dict) and body.get("attachmentId"):
            return True
        for child in (part.get("parts") or []):
            if walk(child):
                return True
        return False
    return walk(payload)


def _gmail_decode_data(data_b64: str) -> str:
    if not data_b64:
        return ""
    s = data_b64.replace("-", "+").replace("_", "/")
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    try:
        return base64.b64decode(s + pad).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _gmail_extract_bodies_and_attachments(payload: Dict[str, Any]) -> Tuple[str, str, List[Dict[str, Any]]]:
    text_chunks: List[str] = []
    html_chunks: List[str] = []
    attachments: List[Dict[str, Any]] = []

    def walk(part: Dict[str, Any]) -> None:
        mime = (part.get("mimeType") or "").lower()
        filename = part.get("filename") or ""
        body = part.get("body") or {}
        data_b64 = body.get("data") if isinstance(body, dict) else None
        attach_id = body.get("attachmentId") if isinstance(body, dict) else None

        if filename or attach_id:
            attachments.append(
                {
                    "filename": filename or "",
                    "mime_type": mime or "",
                    "size_estimate": _safe_int(body.get("size") if isinstance(body, dict) else None, 0),
                    "attachment_id": attach_id or "",
                }
            )

        if mime == "text/plain" and data_b64:
            text_chunks.append(_gmail_decode_data(data_b64))
        elif mime == "text/html" and data_b64:
            html_chunks.append(_gmail_decode_data(data_b64))

        for child in (part.get("parts") or []):
            if isinstance(child, dict):
                walk(child)

    walk(payload)
    return (
        "\n".join([c for c in text_chunks if c]).strip(),
        "\n".join([c for c in html_chunks if c]).strip(),
        attachments,
    )


def _google_event_time_to_str(obj: Any) -> Optional[str]:
    if not isinstance(obj, dict):
        return None
    if obj.get("dateTime"):
        return str(obj["dateTime"])
    if obj.get("date"):
        return str(obj["date"])
    return None


def _google_event_to_common(ev: Dict[str, Any]) -> Dict[str, Any]:
    attendees = [a.get("email") for a in (ev.get("attendees") or []) if a.get("email")]
    return {
        "id": ev.get("id") or "",
        "title": ev.get("summary") or "",
        "start": _google_event_time_to_str(ev.get("start")),
        "end": _google_event_time_to_str(ev.get("end")),
        "location": ev.get("location") or "",
        "attendees": attendees,
    }


# ---------------------------------------------------------------------------
# Microsoft Graph provider
# ---------------------------------------------------------------------------

class _MicrosoftProvider(_Provider):
    def __init__(self, cfg: EmailCalendarConfig, http: httpx.AsyncClient) -> None:
        self.cfg = cfg
        self.http = http
        self.tokens = _OAuthTokenManager(cfg)
        self.base = "https://graph.microsoft.com/v1.0"

    def _folder_segment(self, folder: str) -> str:
        f = (folder or "inbox").strip().lower()
        mapping = {
            "inbox": "inbox",
            "sent": "sentitems",
            "sentitems": "sentitems",
            "drafts": "drafts",
            "junk": "junkemail",
            "spam": "junkemail",
            "deleted": "deleteditems",
            "trash": "deleteditems",
            "archive": "archive",
        }
        return mapping.get(f, f)

    async def _headers(self, *, extra: Optional[Dict[str, str]] = None, force_refresh: bool = False) -> Dict[str, str]:
        tok = await self.tokens.get(self.http, force_refresh=force_refresh)
        h = {"Authorization": f"Bearer {tok}"}
        if extra:
            h.update(extra)
        return h

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        refreshed = False
        url = f"{self.base}{path}"

        for attempt in range(5):
            try:
                resp = await self.http.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=await self._headers(extra=extra_headers, force_refresh=False),
                )
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt >= 4:
                    raise ToolError("Network error talking to Microsoft Graph.")
                await asyncio.sleep(_sleep_for_retry(attempt))
                continue

            if resp.status_code == 401 and not refreshed:
                _ = await self.tokens.get(self.http, force_refresh=True)
                refreshed = True
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt >= 4:
                    _ = _json_or_raise(resp)
                await asyncio.sleep(_sleep_for_retry(attempt, _parse_retry_after(resp.headers)))
                continue

            return _json_or_raise(resp)

        raise ToolError("Microsoft Graph request failed after retries.")

    def _parse_filter(self, filter: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, str]]:
        if not filter:
            return ({}, {})
        f = filter.strip()
        if not f:
            return ({}, {})

        if f.lower() == "unread":
            return ({"$filter": "isRead eq false"}, {})

        m = re.match(r"^(from|to|subject)\s*:\s*(.+)$", f, flags=re.IGNORECASE)
        if m:
            key = m.group(1).lower()
            val = m.group(2).strip().replace("'", "''")
            if key == "from":
                return ({"$filter": f"from/emailAddress/address eq '{val}'"}, {})
            if key == "to":
                return ({"$filter": f"toRecipients/any(r:r/emailAddress/address eq '{val}')"}, {})
            if key == "subject":
                return ({"$filter": f"contains(subject,'{val}')"}, {})

        return ({"$search": f'"{f}"', "$count": "true"}, {"ConsistencyLevel": "eventual"})

    async def email_read(self, count: int, filter: Optional[str], folder: str) -> List[Dict[str, Any]]:
        count = max(1, min(int(count), 50))
        qp: Dict[str, Any] = {
            "$top": count,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,bodyPreview,receivedDateTime,from,toRecipients,hasAttachments,isRead",
        }
        filter_qp, extra_headers = self._parse_filter(filter)
        qp.update(filter_qp)

        seg = self._folder_segment(folder)
        data = await self._request_json("GET", f"/me/mailFolders/{seg}/messages", params=qp, extra_headers=extra_headers)
        items = data.get("value") or []

        out: List[Dict[str, Any]] = []
        for it in items[:count]:
            out.append(
                {
                    "id": it.get("id") or "",
                    "thread_id": it.get("conversationId") or "",
                    "from": ((it.get("from") or {}).get("emailAddress") or {}).get("address") or "",
                    "to": ",".join(
                        [((r.get("emailAddress") or {}).get("address") or "") for r in (it.get("toRecipients") or []) if r]
                    ),
                    "subject": it.get("subject") or "",
                    "preview": _preview_200(it.get("bodyPreview") or ""),
                    "received_at": it.get("receivedDateTime") or "",
                    "has_attachments": bool(it.get("hasAttachments")),
                    "is_unread": not bool(it.get("isRead")),
                }
            )
        return out

    async def email_get(self, message_id: str) -> Dict[str, Any]:
        if not message_id:
            raise ToolError("email.get requires 'message_id'.")

        extra_headers = {"Prefer": 'outlook.body-content-type="text"'}
        qp = {"$select": "id,conversationId,subject,receivedDateTime,from,toRecipients,ccRecipients,hasAttachments,isRead,body"}
        it = await self._request_json("GET", f"/me/messages/{message_id}", params=qp, extra_headers=extra_headers)

        to = ",".join([((r.get("emailAddress") or {}).get("address") or "") for r in (it.get("toRecipients") or []) if r])
        cc = ",".join([((r.get("emailAddress") or {}).get("address") or "") for r in (it.get("ccRecipients") or []) if r])

        body_obj = it.get("body") or {}
        body_text = body_obj.get("content") if isinstance(body_obj, dict) else ""

        return {
            "id": it.get("id") or message_id,
            "thread_id": it.get("conversationId") or "",
            "from": ((it.get("from") or {}).get("emailAddress") or {}).get("address") or "",
            "to": to,
            "cc": cc,
            "subject": it.get("subject") or "",
            "received_at": it.get("receivedDateTime") or "",
            "is_unread": not bool(it.get("isRead")),
            "has_attachments": bool(it.get("hasAttachments")),
            "body_text": body_text or "",
            "body_html": "",
            "attachments": [],
        }

    async def email_send(self, to: str, subject: str, body: str, cc: Optional[str], body_type: str) -> Dict[str, Any]:
        to_list = _split_csv(to)
        if not to_list:
            raise ToolError("email.send requires a non-empty 'to'.")

        content_type = "HTML" if (body_type or "text").lower() == "html" else "Text"
        msg: Dict[str, Any] = {
            "subject": subject or "",
            "body": {"contentType": content_type, "content": body or ""},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to_list],
        }
        if cc:
            cc_list = _split_csv(cc)
            if cc_list:
                msg["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc_list]

        draft = await self._request_json("POST", "/me/messages", json_body=msg)
        mid = draft.get("id") or ""
        if not mid:
            raise ToolError("Microsoft Graph: draft created but no message id returned.")
        await self._request_json("POST", f"/me/messages/{mid}/send")
        return {"message_id": mid, "sent_at": _now_iso_utc()}

    async def email_reply(self, message_id: str, body: str) -> Dict[str, Any]:
        if not message_id:
            raise ToolError("email.reply requires 'message_id'.")

        draft = await self._request_json("POST", f"/me/messages/{message_id}/createReply", json_body={})
        rid = draft.get("id") or ""
        if not rid:
            raise ToolError("Microsoft Graph: createReply returned no draft id.")

        await self._request_json("PATCH", f"/me/messages/{rid}", json_body={"body": {"contentType": "Text", "content": body or ""}})
        await self._request_json("POST", f"/me/messages/{rid}/send")
        return {"message_id": rid, "sent_at": _now_iso_utc()}

    async def calendar_list(self, time_min: datetime, time_max: datetime) -> List[Dict[str, Any]]:
        tmin = time_min.astimezone(timezone.utc)
        tmax = time_max.astimezone(timezone.utc)
        params = {
            "startDateTime": tmin.isoformat(),
            "endDateTime": tmax.isoformat(),
            "$orderby": "start/dateTime",
            "$select": "id,subject,start,end,location,attendees",
        }
        data = await self._request_json("GET", "/me/calendarView", params=params)
        return [_graph_event_to_common(ev) for ev in (data.get("value") or [])]

    async def calendar_freebusy(self, time_min: datetime, time_max: datetime, attendees: List[str]) -> Dict[str, Any]:
        schedules = [a.strip() for a in attendees if a and a.strip()]
        body = {
            "schedules": schedules,
            "startTime": {"dateTime": time_min.astimezone(timezone.utc).replace(tzinfo=None).isoformat(), "timeZone": "UTC"},
            "endTime": {"dateTime": time_max.astimezone(timezone.utc).replace(tzinfo=None).isoformat(), "timeZone": "UTC"},
            "availabilityViewInterval": 30,
        }
        return await self._request_json("POST", "/me/calendar/getSchedule", json_body=body)

    async def calendar_create_event(
        self, title: str, start: str, end: str, attendees: List[str], location: str, body: str
    ) -> Dict[str, Any]:
        start_dt = _parse_iso_datetime(start)
        end_dt = _parse_iso_datetime(end)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        start_utc = start_dt.astimezone(timezone.utc)
        end_utc = end_dt.astimezone(timezone.utc)

        event: Dict[str, Any] = {
            "subject": title,
            "body": {"contentType": "Text", "content": body or ""},
            "start": {"dateTime": start_utc.replace(tzinfo=None).isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_utc.replace(tzinfo=None).isoformat(), "timeZone": "UTC"},
            "location": {"displayName": location or ""},
            "attendees": [{"type": "required", "emailAddress": {"address": a}} for a in attendees if a],
        }
        out = await self._request_json("POST", "/me/events", json_body=event)
        return _graph_event_to_common(out)


def _graph_dt_to_iso(obj: Any) -> Optional[str]:
    if not isinstance(obj, dict):
        return None
    dt = obj.get("dateTime")
    tzname = obj.get("timeZone")
    if not dt:
        return None
    try:
        d = datetime.fromisoformat(str(dt))
        if d.tzinfo is None:
            if tzname and ZoneInfo is not None:
                try:
                    d = d.replace(tzinfo=ZoneInfo(str(tzname)))  # type: ignore[arg-type]
                except Exception:
                    d = d.replace(tzinfo=timezone.utc)
            else:
                d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return str(dt)


def _graph_event_to_common(ev: Dict[str, Any]) -> Dict[str, Any]:
    attendees: List[str] = []
    for a in (ev.get("attendees") or []):
        addr = ((a.get("emailAddress") or {}).get("address") or "")
        if addr:
            attendees.append(addr)
    return {
        "id": ev.get("id") or "",
        "title": ev.get("subject") or "",
        "start": _graph_dt_to_iso(ev.get("start")),
        "end": _graph_dt_to_iso(ev.get("end")),
        "location": ((ev.get("location") or {}).get("displayName") or ""),
        "attendees": attendees,
    }


# ---------------------------------------------------------------------------
# Service router
# ---------------------------------------------------------------------------

class _EmailCalendarService:
    def __init__(self, cfg: EmailCalendarConfig) -> None:
        ensure_email_calendar_auth_configured(cfg)
        self.cfg = cfg

        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(cfg.http_timeout_s),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=int(cfg.max_connections),
                max_keepalive_connections=int(cfg.max_keepalive_connections),
            ),
        )

        if cfg.provider == "gmail":
            self.provider: _Provider = _GmailProvider(cfg, self.http)
        elif cfg.provider == "microsoft":
            self.provider = _MicrosoftProvider(cfg, self.http)
        else:
            raise ToolError(f"Unsupported provider '{cfg.provider}'. {SETUP_DOC_HINT}")

    async def aclose(self) -> None:
        await self.http.aclose()

    async def email_read(self, count: int, filter: Optional[str], folder: str) -> List[Dict[str, Any]]:
        return await self.provider.email_read(count=count, filter=filter, folder=folder)

    async def email_get(self, message_id: str) -> Dict[str, Any]:
        return await self.provider.email_get(message_id=message_id)

    async def email_send(self, to: str, subject: str, body: str, cc: Optional[str], body_type: str) -> Dict[str, Any]:
        return await self.provider.email_send(to=to, subject=subject, body=body, cc=cc, body_type=body_type)

    async def email_reply(self, message_id: str, body: str) -> Dict[str, Any]:
        return await self.provider.email_reply(message_id=message_id, body=body)

    async def calendar_list(self, time_min: datetime, time_max: datetime) -> List[Dict[str, Any]]:
        return await self.provider.calendar_list(time_min=time_min, time_max=time_max)

    async def calendar_freebusy(self, time_min: datetime, time_max: datetime, attendees: List[str]) -> Dict[str, Any]:
        return await self.provider.calendar_freebusy(time_min=time_min, time_max=time_max, attendees=attendees)

    async def calendar_create_event(
        self, title: str, start: str, end: str, attendees: List[str], location: str, body: str
    ) -> Dict[str, Any]:
        return await self.provider.calendar_create_event(
            title=title, start=start, end=end, attendees=attendees, location=location, body=body
        )


_SERVICE: Optional[_EmailCalendarService] = None


def _get_service() -> _EmailCalendarService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = _EmailCalendarService(load_email_calendar_config())
    return _SERVICE


def reset_email_calendar_service_for_tests() -> None:
    global _SERVICE
    _SERVICE = None


# ---------------------------------------------------------------------------
# Consumer-delight scheduling logic (provider-neutral)
# ---------------------------------------------------------------------------

def _merge_busy_intervals(busy: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    if not busy:
        return []
    busy_sorted = sorted(busy, key=lambda x: x[0])
    merged: List[Tuple[datetime, datetime]] = [busy_sorted[0]]
    for s, e in busy_sorted[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


def _invert_to_free(window_start: datetime, window_end: datetime, busy: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    free: List[Tuple[datetime, datetime]] = []
    cur = window_start
    for s, e in busy:
        if e <= cur:
            continue
        if s > cur:
            free.append((cur, min(s, window_end)))
        cur = max(cur, e)
        if cur >= window_end:
            break
    if cur < window_end:
        free.append((cur, window_end))
    return [(s, e) for s, e in free if e > s]


def _round_up(dt: datetime, minutes: int) -> datetime:
    if minutes <= 1:
        return dt
    epoch = int(dt.timestamp())
    step = minutes * 60
    rounded = ((epoch + step - 1) // step) * step
    return datetime.fromtimestamp(rounded, tz=dt.tzinfo)


def _parse_freebusy_payload_to_intervals(payload: Dict[str, Any], tzinfo_: tzinfo) -> List[Tuple[datetime, datetime]]:
    intervals: List[Tuple[datetime, datetime]] = []

    # Google freeBusy
    cals = payload.get("calendars")
    if isinstance(cals, dict):
        for _, v in cals.items():
            for b in (v.get("busy") or []):
                try:
                    s = _parse_iso_datetime(str(b.get("start")))
                    e = _parse_iso_datetime(str(b.get("end")))
                    if s.tzinfo is None:
                        s = s.replace(tzinfo=timezone.utc)
                    if e.tzinfo is None:
                        e = e.replace(tzinfo=timezone.utc)
                    intervals.append((s.astimezone(tzinfo_), e.astimezone(tzinfo_)))
                except Exception:
                    continue

    # Graph getSchedule
    val = payload.get("value")
    if isinstance(val, list):
        for item in val:
            for si in (item.get("scheduleItems") or []):
                try:
                    s_obj = si.get("start") or {}
                    e_obj = si.get("end") or {}
                    s = _parse_iso_datetime(str(s_obj.get("dateTime")))
                    e = _parse_iso_datetime(str(e_obj.get("dateTime")))
                    if s.tzinfo is None:
                        s = s.replace(tzinfo=timezone.utc)
                    if e.tzinfo is None:
                        e = e.replace(tzinfo=timezone.utc)
                    intervals.append((s.astimezone(tzinfo_), e.astimezone(tzinfo_)))
                except Exception:
                    continue

    return intervals


async def _suggest_times(
    svc: _EmailCalendarService,
    *,
    start_date: date,
    days: int,
    duration_minutes: int,
    work_start_hour: int,
    work_end_hour: int,
    attendees: List[str],
    max_suggestions: int,
) -> List[Dict[str, Any]]:
    tzinfo_ = _get_tz(svc.cfg.timezone)
    duration = timedelta(minutes=max(5, int(duration_minutes)))
    suggestions: List[Dict[str, Any]] = []

    for day_offset in range(max(1, int(days))):
        d = start_date + timedelta(days=day_offset)
        day_start = datetime(d.year, d.month, d.day, int(work_start_hour), 0, 0, tzinfo=tzinfo_)
        day_end = datetime(d.year, d.month, d.day, int(work_end_hour), 0, 0, tzinfo=tzinfo_)

        # Busy from your calendar
        events = await svc.calendar_list(time_min=day_start, time_max=day_end)
        busy: List[Tuple[datetime, datetime]] = []
        for ev in events:
            s_raw = ev.get("start")
            e_raw = ev.get("end")
            if not s_raw or not e_raw:
                continue
            try:
                s_dt = _parse_iso_datetime(str(s_raw))
                e_dt = _parse_iso_datetime(str(e_raw))
                if s_dt.tzinfo is None:
                    s_dt = s_dt.replace(tzinfo=timezone.utc)
                if e_dt.tzinfo is None:
                    e_dt = e_dt.replace(tzinfo=timezone.utc)
                busy.append((s_dt.astimezone(tzinfo_), e_dt.astimezone(tzinfo_)))
            except Exception:
                continue

        # Best-effort attendee free/busy merge
        if attendees:
            try:
                fb = await svc.calendar_freebusy(time_min=day_start, time_max=day_end, attendees=attendees)
                busy.extend(_parse_freebusy_payload_to_intervals(fb, tzinfo_))
            except Exception:
                pass

        merged = _merge_busy_intervals(busy)
        free = _invert_to_free(day_start, day_end, merged)

        for fs, fe in free:
            cursor = _round_up(fs, 15)
            while cursor + duration <= fe:
                suggestions.append(
                    {
                        "start": cursor.astimezone(timezone.utc).isoformat(),
                        "end": (cursor + duration).astimezone(timezone.utc).isoformat(),
                        "local_start": cursor.isoformat(),
                        "local_end": (cursor + duration).isoformat(),
                    }
                )
                if len(suggestions) >= int(max_suggestions):
                    return suggestions
                cursor = cursor + timedelta(minutes=15)

    return suggestions


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class EmailReadTool(Tool):
    name = "email.read"
    description = "Read recent email messages (Gmail or Microsoft Graph)."
    params_schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            "filter": {"type": "string", "description": "Examples: 'unread', 'from:boss@company.com', 'subject:invoice'"},
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
    name = "email.send"
    description = "Send an email message."
    params_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "cc": {"type": "string"},
            "body_type": {"type": "string", "enum": ["text", "html"], "default": "text"},
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
            cc=params.get("cc"),
            body_type=str(params.get("body_type") or "text"),
        )


class EmailReplyTool(Tool):
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


class CalendarTodayTool(Tool):
    name = "calendar.today"
    description = "List today's calendar events."
    params_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        svc = _get_service()
        tzinfo_ = _get_tz(svc.cfg.timezone)
        start, end = _start_end_for_day(datetime.now(tzinfo_).date(), tzinfo_)
        return await svc.calendar_list(time_min=start, time_max=end)


class CalendarWeekTool(Tool):
    name = "calendar.week"
    description = "List calendar events for the next 7 days."
    params_schema = {
        "type": "object",
        "properties": {"start_date": {"type": "string", "description": "ISO date YYYY-MM-DD, defaults to today."}},
        "required": [],
        "additionalProperties": False,
    }

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        svc = _get_service()
        tzinfo_ = _get_tz(svc.cfg.timezone)

        sd = params.get("start_date")
        if sd:
            try:
                d = date.fromisoformat(str(sd))
            except Exception:
                raise ToolError(f"Invalid start_date (expected YYYY-MM-DD): {sd!r}")
        else:
            d = datetime.now(tzinfo_).date()

        start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tzinfo_)
        end = start + timedelta(days=7)
        return await svc.calendar_list(time_min=start, time_max=end)


class CalendarCreateEventTool(Tool):
    name = "calendar.create_event"
    description = "Create a calendar event (with conflict check by default)."
    params_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start": {"type": "string", "description": "ISO datetime"},
            "end": {"type": "string", "description": "ISO datetime"},
            "attendees": {"type": "array", "items": {"type": "string"}, "default": []},
            "location": {"type": "string", "default": ""},
            "body": {"type": "string", "default": ""},
            "check_conflicts": {"type": "boolean", "default": True},
        },
        "required": ["title", "start", "end", "attendees", "location", "body"],
        "additionalProperties": False,
    }

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        svc = _get_service()
        title = str(params.get("title") or "").strip()
        start_s = str(params.get("start") or "").strip()
        end_s = str(params.get("end") or "").strip()
        attendees = params.get("attendees") or []
        location = str(params.get("location") or "")
        body = str(params.get("body") or "")
        check_conflicts = bool(params.get("check_conflicts", True))

        if not title or not start_s or not end_s:
            raise ToolError("calendar.create_event requires title, start, end.")
        if not isinstance(attendees, list):
            raise ToolError("calendar.create_event attendees must be a list[str].")

        start_dt = _parse_iso_datetime(start_s)
        end_dt = _parse_iso_datetime(end_s)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        if check_conflicts:
            tzinfo_ = _get_tz(svc.cfg.timezone)
            existing = await svc.calendar_list(time_min=start_dt.astimezone(tzinfo_), time_max=end_dt.astimezone(tzinfo_))
            overlaps = []
            for ev in existing:
                try:
                    s = _parse_iso_datetime(str(ev.get("start")))
                    e = _parse_iso_datetime(str(ev.get("end")))
                    if s.tzinfo is None:
                        s = s.replace(tzinfo=timezone.utc)
                    if e.tzinfo is None:
                        e = e.replace(tzinfo=timezone.utc)
                    if not (e <= start_dt or s >= end_dt):
                        overlaps.append({"id": ev.get("id"), "title": ev.get("title"), "start": ev.get("start"), "end": ev.get("end")})
                except Exception:
                    continue

            if overlaps:
                raise ToolError(
                    "Event conflicts with existing calendar items. "
                    "Use calendar.suggest_times or set check_conflicts=false if intentional. "
                    f"Conflicts: {overlaps[:5]}"
                )

        return await svc.calendar_create_event(
            title=title,
            start=start_s,
            end=end_s,
            attendees=[str(a) for a in attendees],
            location=location,
            body=body,
        )


class CalendarSuggestTimesTool(Tool):
    name = "calendar.suggest_times"
    description = "Suggest meeting times that avoid conflicts (optionally uses attendee free/busy when available)."
    params_schema = {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD, defaults to today."},
            "days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 30},
            "duration_minutes": {"type": "integer", "default": 30, "minimum": 5, "maximum": 240},
            "work_start_hour": {"type": "integer", "default": 9, "minimum": 0, "maximum": 23},
            "work_end_hour": {"type": "integer", "default": 17, "minimum": 1, "maximum": 24},
            "attendees": {"type": "array", "items": {"type": "string"}, "default": []},
            "max_suggestions": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
        },
        "required": [],
        "additionalProperties": False,
    }

    async def run(self, ctx: Any = None, **params: Any) -> Any:
        svc = _get_service()
        tzinfo_ = _get_tz(svc.cfg.timezone)

        sd = params.get("start_date")
        if sd:
            try:
                d = date.fromisoformat(str(sd))
            except Exception:
                raise ToolError(f"Invalid start_date (expected YYYY-MM-DD): {sd!r}")
        else:
            d = datetime.now(tzinfo_).date()

        attendees = params.get("attendees") or []
        if not isinstance(attendees, list):
            raise ToolError("attendees must be a list[str].")

        return await _suggest_times(
            svc,
            start_date=d,
            days=int(params.get("days", 7)),
            duration_minutes=int(params.get("duration_minutes", 30)),
            work_start_hour=int(params.get("work_start_hour", 9)),
            work_end_hour=int(params.get("work_end_hour", 17)),
            attendees=[str(a) for a in attendees],
            max_suggestions=int(params.get("max_suggestions", 10)),
        )


TOOLS: List[Tool] = [
    EmailReadTool(),
    EmailGetTool(),
    EmailSendTool(),
    EmailReplyTool(),
    CalendarTodayTool(),
    CalendarWeekTool(),
    CalendarCreateEventTool(),
    CalendarSuggestTimesTool(),
]


def get_tools() -> List[Tool]:
    return TOOLS
