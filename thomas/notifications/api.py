"""
FastAPI API + initialization for the Smart Notification Center.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from .store import Notification, NotificationCreate, NotificationStore
from .dispatcher import (
    NotificationBroadcaster,
    NotificationDispatcher,
    build_vapid_from_env,
    _env_flag,
)

# Service worker JS (served at /sw.js)
# Keeps everything self-contained (no extra file required).
SERVICE_WORKER_JS = r"""
self.addEventListener('push', function(event) {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}
  const title = data.title || 'Thomas';
  const options = {
    body: data.body || '',
    data: { action_url: data.action_url || '/', id: data.id || null },
    tag: data.id || undefined,
    renotify: false
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const url = (event.notification && event.notification.data && event.notification.data.action_url) || '/';
  event.waitUntil((async () => {
    const allClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of allClients) {
      if ('focus' in c) {
        c.navigate(url);
        return c.focus();
      }
    }
    return clients.openWindow(url);
  })());
});
""".strip()


def _default_db_path() -> str:
    return os.getenv("THOMAS_NOTIFICATIONS_DB") or os.path.join(".", "data", "notifications.sqlite")


def init_notifications(app: FastAPI, db_path: Optional[str] = None) -> None:
    """
    Call once during app initialization.
    - Creates store + dispatcher + broadcaster
    - Mounts API router
    """
    path = db_path or _default_db_path()
    store = NotificationStore(path)
    broadcaster = NotificationBroadcaster()
    vapid = build_vapid_from_env()
    enable_toasts = _env_flag("THOMAS_DESKTOP_TOASTS", "0")
    dispatcher = NotificationDispatcher(store=store, broadcaster=broadcaster, vapid=vapid, enable_desktop_toasts=enable_toasts)

    app.state.notification_store = store
    app.state.notification_broadcaster = broadcaster
    app.state.notification_dispatcher = dispatcher

    app.include_router(build_router(), prefix="")

    # Optional: ensure /sw.js is available at root
    # (already included by build_router)


def build_router() -> APIRouter:
    router = APIRouter()

    def _store(req: Request) -> NotificationStore:
        s = getattr(req.app.state, "notification_store", None)
        if not s:
            raise HTTPException(status_code=500, detail="Notification store not initialized")
        return s

    def _dispatcher(req: Request) -> NotificationDispatcher:
        d = getattr(req.app.state, "notification_dispatcher", None)
        if not d:
            raise HTTPException(status_code=500, detail="Notification dispatcher not initialized")
        return d

    def _broadcaster(req: Request) -> NotificationBroadcaster:
        b = getattr(req.app.state, "notification_broadcaster", None)
        if not b:
            raise HTTPException(status_code=500, detail="Notification broadcaster not initialized")
        return b

    @router.get("/api/notifications", response_model=Dict[str, Any])
    def list_notifications(
        request: Request,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        type: Optional[str] = Query(None),
        severity: Optional[str] = Query(None),
        unread_only: bool = Query(False),
    ):
        store = _store(request)
        items = store.list(limit=limit, offset=offset, type_=type, severity=severity, unread_only=unread_only)
        unread_count = store.unread_count()
        return {"items": [i.dict() for i in items], "unread_count": unread_count}

    @router.get("/api/notifications/unread_count", response_model=Dict[str, int])
    def get_unread_count(request: Request):
        store = _store(request)
        return {"unread_count": store.unread_count()}

    @router.post("/api/notifications", response_model=Notification)
    def create_notification(
        request: Request,
        payload: NotificationCreate = Body(...),
    ):
        dispatcher = _dispatcher(request)
        n = dispatcher.notify(
            type=payload.type,
            title=payload.title,
            body=payload.body,
            severity=payload.severity,
            action_url=payload.action_url,
            deliver_push=True,
            deliver_desktop=True,
        )
        return n

    @router.post("/api/notifications/{notif_id}/read", response_model=Notification)
    def mark_read(request: Request, notif_id: str):
        store = _store(request)
        n = store.mark_read(notif_id)
        if not n:
            raise HTTPException(status_code=404, detail="Notification not found")
        return n

    @router.delete("/api/notifications/clear", response_model=Dict[str, int])
    def clear_notifications(
        request: Request,
        mode: str = Query("all", description="all|read"),
    ):
        store = _store(request)
        deleted = store.clear(mode=mode)
        return {"deleted": deleted}

    # -----------------------------
    # SSE stream
    # -----------------------------
    @router.get("/api/notifications/stream")
    async def stream_notifications(request: Request):
        broadcaster = _broadcaster(request)
        q = await broadcaster.subscribe()

        async def event_gen():
            try:
                # Immediate hello so proxies open the stream
                yield "event: hello\ndata: {}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield f"event: {msg.get('event','notification')}\ndata: {json.dumps(msg.get('data', {}))}\n\n"
                    except asyncio.TimeoutError:
                        # keep-alive ping
                        yield "event: ping\ndata: {}\n\n"
            finally:
                await broadcaster.unsubscribe(q)

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    # -----------------------------
    # Web Push
    # -----------------------------
    @router.get("/api/notifications/push/public-key")
    def push_public_key(request: Request):
        dispatcher = _dispatcher(request)
        if not dispatcher.vapid:
            raise HTTPException(status_code=404, detail="VAPID not configured")
        return {"publicKey": dispatcher.vapid.public_key}

    @router.post("/api/notifications/push/subscribe")
    async def push_subscribe(request: Request, body: Dict[str, Any] = Body(...)):
        """
        Expected browser subscription format:
        {
          "endpoint": "...",
          "keys": { "p256dh": "...", "auth": "..." }
        }
        """
        store = _store(request)
        endpoint = body.get("endpoint")
        keys = body.get("keys") or {}
        p256dh = keys.get("p256dh")
        auth = keys.get("auth")
        if not (endpoint and p256dh and auth):
            raise HTTPException(status_code=400, detail="Invalid subscription payload")

        ua = request.headers.get("user-agent")
        store.upsert_subscription(endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=ua)
        return {"ok": True}

    @router.post("/api/notifications/push/unsubscribe")
    async def push_unsubscribe(request: Request, body: Dict[str, Any] = Body(...)):
        store = _store(request)
        endpoint = body.get("endpoint")
        if not endpoint:
            raise HTTPException(status_code=400, detail="Missing endpoint")
        deleted = store.delete_subscription(endpoint)
        return {"deleted": deleted}

    # Serve SW at root
    @router.get("/sw.js")
    def service_worker():
        return PlainTextResponse(SERVICE_WORKER_JS, media_type="application/javascript")

    return router
