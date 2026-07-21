"""
Automatic delegation lifecycle notifications (CAP-045).

Maps background-delegation lifecycle events to Smart Notification Center
notifications with a deep link back to the originating chat session:

- completed        -> kind "completion"      (severity info)
- failed / blocked -> kind "blocked"         (severity error / warn)
- approval_needed  -> kind "approval_needed" (severity warn)

Everything here is best-effort by contract: ``emit_delegation_notification``
never raises, because a notification failure must never break a delegation.

Delivery goes through :class:`NotificationDispatcher` (persistence, SSE
broadcast, web push, desktop toasts) — never around it.  Deduplication uses
the dispatcher's ``notification_id`` primary key: each (event, execution_id)
pair maps to a deterministic id, so retried terminal events are suppressed.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import uuid
from typing import Any
from urllib.parse import quote

from .dispatcher import NotificationDispatcher
from .store import NotificationStore

log = logging.getLogger(__name__)

DEFAULT_WEB_BASE_URL = "http://127.0.0.1:8899"

# event name -> (notification kind, severity)
EVENT_KINDS: dict[str, tuple[str, str]] = {
    "completed": ("completion", "info"),
    "failed": ("blocked", "error"),
    "blocked": ("blocked", "warn"),
    "approval_needed": ("approval_needed", "warn"),
}

_EVENT_TITLES: dict[str, str] = {
    "completed": "Task completed",
    "failed": "Task blocked",
    "blocked": "Task blocked",
    "approval_needed": "Approval needed",
}

_EVENT_FALLBACK_BODIES: dict[str, str] = {
    "completed": "The delegated task finished successfully.",
    "failed": "The delegated task stopped and needs attention.",
    "blocked": "The delegated task is blocked and needs attention.",
    "approval_needed": "A delegated task is waiting for your approval.",
}

# Failures the best-effort path swallows (with logging).  Kept specific on
# purpose: the repo exception gate forbids blanket ``except Exception``
# without re-raise, and these cover the realistic dispatcher/store failures.
_HOOK_EXCEPTIONS = (
    sqlite3.Error,
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
)

_dispatcher_lock = threading.Lock()
_active_dispatcher: NotificationDispatcher | None = None
_fallback_dispatcher: NotificationDispatcher | None = None


def _default_db_path() -> str:
    return os.getenv("THOMAS_NOTIFICATIONS_DB") or os.path.join(".", "data", "notifications.sqlite")


def set_active_dispatcher(dispatcher: NotificationDispatcher | None) -> None:
    """
    Register the app-level dispatcher so delegation hooks share its store,
    broadcaster, and push configuration.  ``init_notifications`` calls this.
    Passing ``None`` clears the registration (used by tests).
    """
    global _active_dispatcher
    with _dispatcher_lock:
        _active_dispatcher = dispatcher


def get_dispatcher() -> NotificationDispatcher:
    """
    Return the registered app dispatcher, or a lazily created process-wide
    fallback that persists to the default notifications database.
    """
    global _fallback_dispatcher
    with _dispatcher_lock:
        if _active_dispatcher is not None:
            return _active_dispatcher
        if _fallback_dispatcher is None:
            _fallback_dispatcher = NotificationDispatcher(store=NotificationStore(_default_db_path()))
        return _fallback_dispatcher


def web_base_url() -> str:
    return (os.getenv("THOMAS_WEB_BASE_URL") or DEFAULT_WEB_BASE_URL).strip().rstrip("/")


def session_deep_link(session_id: str) -> str:
    """Deep link to the chat session in the web UI."""
    base = web_base_url()
    sid = (session_id or "").strip()
    if not sid:
        return f"{base}/"
    return f"{base}/?session={quote(sid, safe='')}"


def _task_label(record: dict[str, Any]) -> str:
    summary = str(record.get("summary") or "").strip()
    if summary:
        return summary if len(summary) <= 120 else summary[:117] + "..."
    task_id = str(record.get("task_id") or "").strip()
    if task_id:
        return f"task {task_id}"
    return "background task"


def build_notification(event: str, record: dict[str, Any], text: str = "") -> dict[str, Any] | None:
    """
    Build the notification payload for a lifecycle event, or ``None`` when
    the event has no notification mapping.
    """
    event = (event or "").strip().lower()
    mapped = EVENT_KINDS.get(event)
    if mapped is None:
        return None
    kind, severity = mapped

    label = _task_label(record)
    title = f"{_EVENT_TITLES[event]}: {label}"
    body = str(text or "").strip() or str(record.get("last_progress") or "").strip()
    if not body:
        body = _EVENT_FALLBACK_BODIES[event]

    execution_id = str(record.get("execution_id") or "").strip()
    notification_id = f"delegation:{event}:{execution_id}" if execution_id else uuid.uuid4().hex

    return {
        "type": kind,
        "title": title,
        "body": body,
        "severity": severity,
        "action_url": session_deep_link(str(record.get("session_id") or "")),
        "notification_id": notification_id,
    }


def emit_delegation_notification(
    event: str,
    record: dict[str, Any],
    *,
    text: str = "",
    dispatcher: NotificationDispatcher | None = None,
) -> Any | None:
    """
    Emit a notification for a delegation lifecycle event.

    Best-effort: returns the created Notification, or ``None`` when the event
    is unmapped, a duplicate, or emission failed.  Never raises.
    """
    payload = None
    try:
        payload = build_notification(event, record, text=text)
        if payload is None:
            return None
        active = dispatcher or get_dispatcher()
        return active.notify(
            type=payload["type"],
            title=payload["title"],
            body=payload["body"],
            severity=payload["severity"],
            action_url=payload["action_url"],
            notification_id=payload["notification_id"],
        )
    except sqlite3.IntegrityError:
        # Deterministic notification_id already stored: duplicate terminal
        # event (e.g. a retried completion) — intentionally suppressed.
        log.debug("duplicate delegation notification suppressed: %s", payload and payload["notification_id"])
        return None
    except _HOOK_EXCEPTIONS:
        log.warning(
            "delegation notification emission failed (event=%s, execution_id=%s)",
            event,
            record.get("execution_id", ""),
            exc_info=True,
        )
        return None
