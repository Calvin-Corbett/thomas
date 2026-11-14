"""Per-session serialisation for chat turns.

Chat V2 never adopted the session-run guard the legacy chat handler used, so two
requests for the SAME session both executed a turn and could interleave
conversation state.

This wraps a turn handler so turns for one session run one at a time. It
deliberately SERIALISES rather than rejecting the follow-up: Chat V2 has no
queue to drain a rejected message, so returning "busy" would silently discard
what the user typed. The follow-up waits for the turn in front of it and then
runs normally.

Two properties keep this safe:

* **per-session** -- unrelated sessions still run in parallel; this must never
  become a global chat bottleneck.
* **fails open** -- if the lock registry is unavailable the turn runs anyway. A
  missing guard degrades to today's behaviour rather than wedging chat.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from aiohttp import web

try:
    from thomas.server.app_keys import APP_SESSION_LOCKS, APP_SESSION_LOCKS_LOCK
except ImportError:  # pragma: no cover - import guard
    APP_SESSION_LOCKS = APP_SESSION_LOCKS_LOCK = None  # type: ignore[assignment]

TurnHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]

_BODY_FAULTS = (json.JSONDecodeError, ValueError, TypeError, UnicodeDecodeError)


def peek_session_id(payload: Any) -> str:
    """Read the session id from an already-parsed body, if present."""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("session_id") or payload.get("sessionId") or "").strip()


async def session_turn_lock(app: web.Application, session_id: str) -> asyncio.Lock | None:
    """Return the per-session turn lock, creating it on first use.

    ``None`` means the registry is unavailable and the caller should proceed
    without serialising.
    """
    if APP_SESSION_LOCKS is None or APP_SESSION_LOCKS_LOCK is None:
        return None
    locks = app.get(APP_SESSION_LOCKS)
    registry_lock = app.get(APP_SESSION_LOCKS_LOCK)
    if locks is None or registry_lock is None:
        return None
    async with registry_lock:
        lock = locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            locks[session_id] = lock
        return lock


async def _until_disconnect(
    request: web.Request, run: Callable[[], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    """Cancel only this foreground Chat request when its client disconnects.

    aiohttp leaves handlers running on disconnect by default. In Chat that
    wastes the ongoing generation and holds the session lock against a next
    send, even when the user has already pressed Stop. Independent delegated
    tasks are not children of this request and are deliberately left alone.
    """
    transport = getattr(request, "transport", None)
    owner = asyncio.current_task()
    if transport is None or owner is None:
        return await run()

    async def watch() -> None:
        while not transport.is_closing():
            await asyncio.sleep(0.05)
        owner.cancel()

    watcher = asyncio.create_task(watch(), name="chat-client-disconnect")
    try:
        return await run()
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher


def session_serialised(turn_handler: TurnHandler) -> TurnHandler:
    """Wrap ``turn_handler`` so turns for one session never overlap."""

    async def _guarded(request: web.Request) -> web.StreamResponse:
        try:
            payload = await request.json()
        except _BODY_FAULTS:
            # Malformed body -- let the turn handler emit the canonical 400.
            return await turn_handler(request)

        sid = peek_session_id(payload)
        if not sid:
            # A fresh session cannot contend with anything.
            return await turn_handler(request)

        lock = await session_turn_lock(request.app, sid)
        if lock is None:
            return await turn_handler(request)

        async with lock:
            return await turn_handler(request)

    async def _client_owned(request: web.Request) -> web.StreamResponse:
        return await _until_disconnect(request, lambda: _guarded(request))

    _client_owned.__name__ = getattr(turn_handler, "__name__", "chat_turn")
    _client_owned.__doc__ = turn_handler.__doc__
    return _client_owned
