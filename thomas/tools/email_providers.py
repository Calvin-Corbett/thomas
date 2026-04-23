"""Email provider implementations for Gmail and Microsoft Graph.

This module contains the base provider interface and concrete implementations
for Gmail (Google API) and Microsoft Graph (Azure AD).
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

try:
    from thomas.tools.base import Tool, ToolError  # type: ignore
except ImportError:  # pragma: no cover

    class ToolError(RuntimeError):
        pass


def _fold_csv(s: str) -> str:
    """Normalize whitespace in CSV headers."""
    return ", ".join(p.strip() for p in s.split(",") if p.strip())


def _split_csv(s: str) -> list[str]:
    """Split CSV string and strip whitespace."""
    return [p.strip() for p in s.split(",") if p.strip()]


def _b64url(b: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _preview_200(s: str) -> str:
    """Get first 200 characters of string."""
    return (s or "")[:200]


def _safe_int(x: Any, default: int) -> int:
    """Safely convert value to int, returning default on failure."""
    try:
        return int(x)
    except (ValueError, TypeError):
        return default


class _Provider:
    """Base provider interface for email operations."""

    def __init__(self, token_mgr: Any) -> None:
        self.token_mgr = token_mgr

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make an HTTP request with automatic token refresh."""
        raise NotImplementedError

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """Make an HTTP request and parse JSON response."""
        resp = await self._request(method, url, **kwargs)
        if resp.status_code >= 400:
            try:
                data = resp.json()
                msg = data.get("error", {}).get("message") or str(data)
            except Exception:
                msg = resp.text[:500]
            raise ToolError(f"{resp.status_code}: {msg}")
        return resp.json()

    async def email_read(self, count: int, filter: str | None, folder: str) -> list[dict[str, Any]]:
        """Read recent email messages."""
        raise NotImplementedError

    async def email_get(self, message_id: str) -> dict[str, Any]:
        """Get a single email by ID."""
        raise NotImplementedError

    async def email_send(self, to: str, subject: str, body: str) -> dict[str, Any]:
        """Send an email."""
        raise NotImplementedError

    async def email_reply(self, message_id: str, body: str) -> dict[str, Any]:
        """Reply to an email."""
        raise NotImplementedError

    async def calendar_list_events(self, days: int, tz: str) -> list[dict[str, Any]]:
        """List calendar events for the next N days."""
        raise NotImplementedError

    async def calendar_freebusy(self, calendars: list[str], start: str, end: str, tz: str) -> list[tuple[str, str]]:
        """Get busy intervals for calendars."""
        raise NotImplementedError

    async def calendar_create_event(
        self, title: str, start: str, end: str, description: str, tz: str
    ) -> dict[str, Any]:
        """Create a calendar event."""
        raise NotImplementedError


class _GmailProvider(_Provider):
    """Gmail provider using Google API."""

    def __init__(self, token_mgr: Any) -> None:
        super().__init__(token_mgr)
        self._sem = asyncio.Semaphore(6)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make a request to Gmail API with token refresh."""
        token = await self.token_mgr.get_token("gmail")
        h = {"Authorization": f"Bearer {token}"}
        if headers:
            h.update(headers)
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.request(method, url, params=params, json=json, headers=h)

    async def email_read(self, count: int, filter: str | None, folder: str) -> list[dict[str, Any]]:
        """Read recent email messages (Gmail)."""
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
            "id,threadId,internalDate,snippet,labelIds," "payload(headers,name,value,parts,filename,body/attachmentId)"
        )

        async def fetch(mid: str) -> dict[str, Any]:
            async with self._sem:
                data = await self._request_json(
                    "GET",
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
                    params={"format": "full", "fields": fields},
                )
                payload = data.get("payload") or {}
                headers = {h.get("name", "").lower(): h.get("value", "") for h in (payload.get("headers") or [])}
                received = (
                    _try_rfc2822_to_iso(headers.get("date", "") or "")
                    or _try_internal_ms_to_iso(data.get("internalDate"))
                    or ""
                )

                label_ids = data.get("labelIds") or []
                is_unread = "UNREAD" in set(label_ids)

                return {
                    "id": data.get("id") or mid,
                    "thread_id": data.get("threadId") or "",
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "cc": _fold_csv(headers.get("cc", "")),
                    "subject": headers.get("subject", ""),
                    "received": received,
                    "snippet": data.get("snippet", "")[:300],
                    "has_attachments": _gmail_has_attachments(payload),
                    "is_unread": is_unread,
                }

        return await asyncio.gather(*[fetch(mid) for mid in ids])

    async def email_get(self, message_id: str) -> dict[str, Any]:
        """Fetch a full email (Gmail)."""
        data = await self._request_json(
            "GET",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            params={"format": "full"},
        )
        payload = data.get("payload") or {}
        headers = {h.get("name", "").lower(): h.get("value", "") for h in (payload.get("headers") or [])}
        received = (
            _try_rfc2822_to_iso(headers.get("date", "") or "")
            or _try_internal_ms_to_iso(data.get("internalDate"))
            or ""
        )
        body_text, body_html, attachments = _gmail_extract_bodies_and_attachments(payload)

        return {
            "id": data.get("id") or message_id,
            "thread_id": data.get("threadId") or "",
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "cc": _fold_csv(headers.get("cc", "")),
            "bcc": _fold_csv(headers.get("bcc", "")),
            "subject": headers.get("subject", ""),
            "received": received,
            "body_text": body_text[:8000],
            "body_html": body_html[:2000],
            "attachments": attachments,
        }

    async def email_send(self, to: str, subject: str, body: str) -> dict[str, Any]:
        """Send an email (Gmail)."""
        msg = EmailMessage()
        msg["to"] = to
        msg["subject"] = subject
        msg.set_content(body)

        b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
        result = await self._request_json(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json={"raw": b64},
        )
        return {"id": result.get("id") or "", "thread_id": result.get("threadId") or ""}

    async def email_reply(self, message_id: str, body: str) -> dict[str, Any]:
        """Reply to an email (Gmail)."""
        orig = await self.email_get(message_id)
        to = orig.get("from") or ""
        subject = orig.get("subject") or ""
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        msg = EmailMessage()
        msg["to"] = to
        msg["subject"] = subject
        msg["in-reply-to"] = f"<{message_id}@mail.gmail.com>"
        msg["references"] = f"<{message_id}@mail.gmail.com>"
        msg.set_content(body)

        b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
        result = await self._request_json(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json={"raw": b64},
        )
        return {"id": result.get("id") or "", "thread_id": result.get("threadId") or ""}

    async def calendar_list_events(self, days: int, tz: str) -> list[dict[str, Any]]:
        """List calendar events for the next N days (Gmail/Google Calendar)."""
        from datetime import timedelta as td

        from .email_calendar import _get_tz

        days = max(1, min(int(days), 90))
        tz_info = _get_tz(tz)

        now_utc = datetime.now(timezone.utc)
        end_utc = now_utc + td(days=days)

        data = await self._request_json(
            "GET",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params={
                "timeMin": now_utc.isoformat(),
                "timeMax": end_utc.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 250,
            },
        )

        events = []
        for ev in data.get("items") or []:
            events.append(_google_event_to_common(ev))

        return events

    async def calendar_freebusy(self, calendars: list[str], start: str, end: str, tz: str) -> list[tuple[str, str]]:
        """Get busy intervals for calendars (Gmail/Google Calendar)."""
        from .email_calendar import _get_tz

        if not calendars:
            calendars = ["primary"]

        items = [{"id": c} for c in calendars]
        payload = {
            "timeMin": start,
            "timeMax": end,
            "items": items,
        }

        data = await self._request_json(
            "POST",
            "https://www.googleapis.com/calendar/v3/freeBusy",
            json=payload,
        )

        tz_info = _get_tz(tz)
        busy = []
        for cal_id in calendars:
            intervals = data.get("calendars", {}).get(cal_id, {}).get("busy") or []
            for interval in intervals:
                busy.append((_parse_iso_datetime(interval["start"]), _parse_iso_datetime(interval["end"])))

        return busy

    async def calendar_create_event(
        self, title: str, start: str, end: str, description: str, tz: str
    ) -> dict[str, Any]:
        """Create a calendar event (Gmail/Google Calendar)."""
        ev = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }

        result = await self._request_json(
            "POST",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            json=ev,
        )

        return {"id": result.get("id") or "", "html_link": result.get("htmlLink") or ""}

    def _gmail_query(self, filter: str | None, folder: str) -> str | None:
        """Build a Gmail query string."""
        parts: list[str] = []
        fldr = (folder or "inbox").strip().lower()
        if fldr and fldr not in {"all", "allmail", "all_mail"}:
            parts.append(f"in:{fldr}")
        if filter:
            f = filter.strip()
            if f:
                parts.append("is:unread" if f.lower() == "unread" else f)
        q = " ".join(parts).strip()
        return q or None


class _MicrosoftProvider(_Provider):
    """Microsoft Graph provider for Outlook/Azure AD."""

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make a request to Microsoft Graph with token refresh."""
        token = await self.token_mgr.get_token("microsoft")
        h = {"Authorization": f"Bearer {token}"}
        if headers:
            h.update(headers)
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.request(method, url, params=params, json=json, headers=h)

    async def email_read(self, count: int, filter: str | None, folder: str) -> list[dict[str, Any]]:
        """Read recent email messages (Microsoft Graph)."""
        count = max(1, min(int(count), 50))

        folder_id = folder.strip().lower() if folder else "inbox"
        if folder_id == "inbox":
            folder_id = "inbox"

        url = f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder_id}/messages"

        data = await self._request_json(
            "GET",
            url,
            params={
                "$top": count,
                "$orderby": "receivedDateTime desc",
                "$select": "id,conversationId,from,toRecipients,ccRecipients,subject,receivedDateTime,isRead,hasAttachments,bodyPreview",
            },
        )

        messages = []
        for msg in data.get("value") or []:
            messages.append(
                {
                    "id": msg.get("id") or "",
                    "thread_id": msg.get("conversationId") or "",
                    "from": msg.get("from", {}).get("emailAddress", {}).get("address") or "",
                    "to": _fold_csv(
                        ", ".join(r.get("emailAddress", {}).get("address") or "" for r in msg.get("toRecipients") or [])
                    ),
                    "cc": _fold_csv(
                        ", ".join(r.get("emailAddress", {}).get("address") or "" for r in msg.get("ccRecipients") or [])
                    ),
                    "subject": msg.get("subject") or "",
                    "received": _graph_dt_to_iso(msg.get("receivedDateTime")) or "",
                    "snippet": msg.get("bodyPreview", "")[:300],
                    "has_attachments": bool(msg.get("hasAttachments")),
                    "is_unread": not bool(msg.get("isRead")),
                }
            )

        return messages

    async def email_get(self, message_id: str) -> dict[str, Any]:
        """Fetch a full email (Microsoft Graph)."""
        msg = await self._request_json(
            "GET",
            f"https://graph.microsoft.com/v1.0/me/messages/{message_id}",
            params={"$select": "*"},
        )

        body_text = msg.get("bodyPreview") or ""
        if msg.get("body", {}).get("content"):
            body_text = msg.get("body", {}).get("content", "")[:8000]

        body_html = ""
        if msg.get("body", {}).get("contentType") == "html":
            body_html = msg.get("body", {}).get("content", "")[:2000]

        attachments = []
        if msg.get("hasAttachments"):
            attach_data = await self._request_json(
                "GET",
                f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/attachments",
            )
            for att in attach_data.get("value") or []:
                attachments.append(
                    {
                        "id": att.get("id") or "",
                        "filename": att.get("name") or "",
                        "size": _safe_int(att.get("size"), 0),
                    }
                )

        return {
            "id": msg.get("id") or message_id,
            "thread_id": msg.get("conversationId") or "",
            "from": msg.get("from", {}).get("emailAddress", {}).get("address") or "",
            "to": _fold_csv(
                ", ".join(r.get("emailAddress", {}).get("address") or "" for r in msg.get("toRecipients") or [])
            ),
            "cc": _fold_csv(
                ", ".join(r.get("emailAddress", {}).get("address") or "" for r in msg.get("ccRecipients") or [])
            ),
            "bcc": _fold_csv(
                ", ".join(r.get("emailAddress", {}).get("address") or "" for r in msg.get("bccRecipients") or [])
            ),
            "subject": msg.get("subject") or "",
            "received": _graph_dt_to_iso(msg.get("receivedDateTime")) or "",
            "body_text": body_text,
            "body_html": body_html,
            "attachments": attachments,
        }

    async def email_send(self, to: str, subject: str, body: str) -> dict[str, Any]:
        """Send an email (Microsoft Graph)."""
        msg_data = {
            "subject": subject,
            "body": {"contentType": "text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }

        result = await self._request_json(
            "POST",
            "https://graph.microsoft.com/v1.0/me/sendMail",
            json={"message": msg_data},
        )

        return {"id": "", "thread_id": ""}

    async def email_reply(self, message_id: str, body: str) -> dict[str, Any]:
        """Reply to an email (Microsoft Graph)."""
        reply_data = {
            "comment": body,
        }

        await self._request_json(
            "POST",
            f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/reply",
            json=reply_data,
        )

        return {"id": "", "thread_id": ""}

    async def calendar_list_events(self, days: int, tz: str) -> list[dict[str, Any]]:
        """List calendar events for the next N days (Microsoft Graph)."""
        from datetime import timedelta as td

        days = max(1, min(int(days), 90))

        now_utc = datetime.now(timezone.utc)
        end_utc = now_utc + td(days=days)

        data = await self._request_json(
            "GET",
            "https://graph.microsoft.com/v1.0/me/calendarview",
            params={
                "startDateTime": now_utc.isoformat(),
                "endDateTime": end_utc.isoformat(),
                "$orderby": "start/dateTime",
                "$top": 250,
            },
        )

        events = []
        for ev in data.get("value") or []:
            events.append(_graph_event_to_common(ev))

        return events

    async def calendar_freebusy(self, calendars: list[str], start: str, end: str, tz: str) -> list[tuple[str, str]]:
        """Get busy intervals for calendars (Microsoft Graph)."""
        if not calendars:
            calendars = ["user@company.onmicrosoft.com"]

        payload = {
            "schedules": calendars,
            "startTime": {"dateTime": start, "timeZone": tz},
            "endTime": {"dateTime": end, "timeZone": tz},
            "availabilityViewInterval": 15,
        }

        data = await self._request_json(
            "POST",
            "https://graph.microsoft.com/v1.0/me/calendar/getSchedule",
            json=payload,
        )

        busy = []
        for item in data.get("value") or []:
            avail_view = item.get("availabilityView") or ""
            if avail_view:
                intervals = _parse_microsoft_availability_view(start, end, avail_view)
                busy.extend(intervals)

        return busy

    async def calendar_create_event(
        self, title: str, start: str, end: str, description: str, tz: str
    ) -> dict[str, Any]:
        """Create a calendar event (Microsoft Graph)."""
        ev = {
            "subject": title,
            "bodyPreview": description,
            "start": {"dateTime": start, "timeZone": tz},
            "end": {"dateTime": end, "timeZone": tz},
        }

        result = await self._request_json(
            "POST",
            "https://graph.microsoft.com/v1.0/me/events",
            json=ev,
        )

        return {"id": result.get("id") or "", "html_link": result.get("webLink") or ""}


def _try_rfc2822_to_iso(s: str) -> str | None:
    """Try to parse RFC 2822 date and convert to ISO 8601."""
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(s)
        return dt.isoformat()
    except (ValueError, TypeError):
        return None


def _try_internal_ms_to_iso(ms: Any) -> str | None:
    """Try to convert Gmail internal milliseconds to ISO 8601."""
    try:
        ts = int(ms) / 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return None


def _gmail_has_attachments(payload: dict[str, Any]) -> bool:
    """Check if Gmail message has attachments."""
    if payload.get("body", {}).get("attachmentId"):
        return True
    for part in payload.get("parts") or []:
        if part.get("body", {}).get("attachmentId"):
            return True
    return False


def _gmail_decode_data(data_b64: str) -> str:
    """Decode base64url Gmail data."""
    try:
        data = base64.urlsafe_b64decode(data_b64 + "===")
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _gmail_extract_bodies_and_attachments(payload: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    """Extract text body, HTML body, and attachments from Gmail payload."""
    body_text = ""
    body_html = ""
    attachments = []

    def extract(part: dict[str, Any]) -> None:
        nonlocal body_text, body_html
        mime = part.get("mimeType", "")

        if mime == "text/plain":
            data = part.get("body", {}).get("data") or ""
            if data:
                body_text = _gmail_decode_data(data)
        elif mime == "text/html":
            data = part.get("body", {}).get("data") or ""
            if data:
                body_html = _gmail_decode_data(data)
        elif mime.startswith("multipart/"):
            for p in part.get("parts") or []:
                extract(p)
        elif part.get("body", {}).get("attachmentId"):
            attachments.append(
                {
                    "id": part.get("body", {}).get("attachmentId") or "",
                    "filename": part.get("filename") or "unnamed",
                    "size": _safe_int(part.get("body", {}).get("size"), 0),
                }
            )

    extract(payload)
    return body_text, body_html, attachments


def _google_event_time_to_str(obj: Any) -> str | None:
    """Convert Google Calendar event time to ISO string."""
    if isinstance(obj, dict):
        return obj.get("dateTime") or obj.get("date")
    return None


def _google_event_to_common(ev: dict[str, Any]) -> dict[str, Any]:
    """Convert Google Calendar event to common format."""
    return {
        "id": ev.get("id") or "",
        "title": ev.get("summary") or "",
        "start": _google_event_time_to_str(ev.get("start")) or "",
        "end": _google_event_time_to_str(ev.get("end")) or "",
        "description": ev.get("description") or "",
        "location": ev.get("location") or "",
        "organizer": ev.get("organizer", {}).get("email") or "",
    }


def _graph_dt_to_iso(obj: Any) -> str | None:
    """Convert Microsoft Graph datetime to ISO string."""
    if isinstance(obj, str):
        return obj
    return None


def _graph_event_to_common(ev: dict[str, Any]) -> dict[str, Any]:
    """Convert Microsoft Graph event to common format."""
    return {
        "id": ev.get("id") or "",
        "title": ev.get("subject") or "",
        "start": ev.get("start", {}).get("dateTime") or "",
        "end": ev.get("end", {}).get("dateTime") or "",
        "description": ev.get("bodyPreview") or "",
        "location": ev.get("locations", [{}])[0].get("displayName") or "",
        "organizer": ev.get("organizer", {}).get("emailAddress", {}).get("address") or "",
    }


def _parse_iso_datetime(s: str) -> datetime:
    """Parse ISO 8601 datetime string."""
    try:
        if "T" in s:
            if "+" in s or s.endswith("Z"):
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    return datetime.now(timezone.utc)


def _parse_microsoft_availability_view(start: str, end: str, avail_view: str) -> list[tuple[datetime, datetime]]:
    """Parse Microsoft availability view string (0=free, 1=tentative, 2=busy, 3=out of office, 4=unknown)."""
    busy = []
    start_dt = _parse_iso_datetime(start)
    end_dt = _parse_iso_datetime(end)

    if not avail_view:
        return busy

    total_seconds = int((end_dt - start_dt).total_seconds())
    slot_seconds = total_seconds // len(avail_view) if avail_view else 900

    current_dt = start_dt
    for char in avail_view:
        status = char
        if status in {"2", "3"}:
            next_dt = current_dt + timedelta(seconds=slot_seconds)
            busy.append((current_dt, next_dt))
        current_dt += timedelta(seconds=slot_seconds)

    return busy
