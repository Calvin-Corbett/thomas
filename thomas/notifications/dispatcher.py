"""
Notification Dispatcher

Single entry point to:
- persist notifications
- broadcast to SSE subscribers
- optionally send Web Push notifications (pywebpush)
- optionally send Desktop toast notifications (plyer)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

from .store import Notification, NotificationCreate, NotificationStore

try:
    from pywebpush import WebPushException, webpush  # type: ignore
except ImportError:  # pragma: no cover
    webpush = None
    WebPushException = Exception  # type: ignore

try:
    from plyer import notification as plyer_notification  # type: ignore
except ImportError:  # pragma: no cover
    plyer_notification = None


def _model_to_dict(model: Any) -> dict[str, Any]:
    model_dump = getattr(model, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    legacy_dict = getattr(model, "dict", None)
    if callable(legacy_dict):
        return dict(legacy_dict())
    if isinstance(model, dict):
        return dict(model)
    return {}


def _env_flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or default).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class VapidConfig:
    public_key: str
    private_key: str
    subject: str


class NotificationBroadcaster:
    """
    Simple in-process broadcast hub for SSE clients.
    Each subscriber gets an asyncio.Queue of JSON-serializable dicts.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    async def publish(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop oldest by draining a bit, then try once
                try:
                    _ = q.get_nowait()
                    q.put_nowait(payload)
                except (ValueError, TypeError):
                    pass


class NotificationDispatcher:
    def __init__(
        self,
        store: NotificationStore,
        broadcaster: NotificationBroadcaster | None = None,
        vapid: VapidConfig | None = None,
        enable_desktop_toasts: bool = False,
    ) -> None:
        self.store = store
        self.broadcaster = broadcaster or NotificationBroadcaster()
        self.vapid = vapid
        self.enable_desktop_toasts = enable_desktop_toasts

    def notify(
        self,
        type: str,
        title: str,
        body: str,
        severity: str = "info",
        action_url: str | None = None,
        *,
        notification_id: str | None = None,
        timestamp_ms: int | None = None,
        deliver_push: bool = True,
        deliver_desktop: bool = True,
    ) -> Notification:
        """
        Persist + broadcast + (optional) deliver to extra channels.
        Storage is the source of truth; delivery is best-effort.
        """
        notif_id = notification_id or uuid.uuid4().hex
        payload = NotificationCreate(type=type, title=title, body=body, severity=severity, action_url=action_url)
        notif = self.store.add(notif_id, payload, timestamp_ms=timestamp_ms)

        # Broadcast to any SSE clients (async, but we can fire-and-forget)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcaster.publish({"event": "notification", "data": _model_to_dict(notif)}))
        except (RuntimeError, ValueError, TypeError):
            # No running event loop (e.g., sync worker thread) or invalid loop state.
            # Broadcast is best-effort and must never break notification persistence.
            pass

        # Optional deliveries
        if deliver_push:
            self._deliver_web_push_best_effort(notif)
        if self.enable_desktop_toasts and deliver_desktop:
            self._deliver_desktop_toast_best_effort(notif)

        return notif

    def _deliver_desktop_toast_best_effort(self, notif: Notification) -> None:
        if not plyer_notification:
            return
        try:
            plyer_notification.notify(
                title=str(notif.title),
                message=str(notif.body),
                app_name="Thomas",
                timeout=6,
            )
        except (ValueError, TypeError):
            # Best-effort only
            return

    def _deliver_web_push_best_effort(self, notif: Notification) -> None:
        if not self.vapid or not webpush:
            return

        # Build a compact payload
        payload = {
            "id": notif.id,
            "type": notif.type,
            "title": notif.title,
            "body": notif.body,
            "severity": notif.severity,
            "timestamp": notif.timestamp,
            "action_url": notif.action_url,
        }
        subs = self.store.list_subscriptions()
        if not subs:
            return

        for s in subs:
            subscription_info = {
                "endpoint": s.endpoint,
                "keys": {
                    "p256dh": s.p256dh,
                    "auth": s.auth,
                },
            }
            try:
                webpush(
                    subscription_info=subscription_info,
                    data=json.dumps(payload),
                    vapid_private_key=self.vapid.private_key,
                    vapid_claims={"sub": self.vapid.subject},
                    ttl=60,
                )
            except WebPushException as e:
                # Remove stale subscriptions if possible
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (404, 410):
                    try:
                        self.store.delete_subscription(s.endpoint)
                    except json.JSONDecodeError:
                        pass
            except json.JSONDecodeError:
                continue


# -----------------------------
# App-level singletons (optional convenience)
# -----------------------------


def build_vapid_from_env() -> VapidConfig | None:
    pub = (os.getenv("THOMAS_VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.getenv("THOMAS_VAPID_PRIVATE_KEY") or "").strip()
    sub = (os.getenv("THOMAS_VAPID_SUBJECT") or "mailto:admin@example.com").strip()
    if pub and priv:
        return VapidConfig(public_key=pub, private_key=priv, subject=sub)
    return None


def get_dispatcher(app: Any) -> NotificationDispatcher:
    """
    Retrieve the dispatcher stored on FastAPI app.state.
    """
    d = getattr(getattr(app, "state", None), "notification_dispatcher", None)
    if not d:
        raise RuntimeError("Notification dispatcher not initialized. Call init_notifications(app) first.")
    return d
