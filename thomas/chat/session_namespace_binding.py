"""Atomic namespace reservation for shared Chat/Work/workspace sessions."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from thomas.chat.conversation import ConversationManager
from thomas.chat.session_store import SessionMeta


async def bind_surface_namespace(
    store: Any,
    session_id: str,
    *,
    surface_mode: str,
    context_id: str | None,
) -> tuple[ConversationManager, SessionMeta] | None:
    """Persist the first namespace claim while holding SessionStore's SID lock."""

    lock = store._lock_for(session_id)
    async with lock:
        target = store._session_path(session_id)
        conversation = ConversationManager()
        meta: SessionMeta | None = None
        if target.exists():
            try:
                raw = await asyncio.to_thread(target.read_text, "utf-8")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("invalid session payload")
                conv_data = data.get("conversation")
                if isinstance(conv_data, dict):
                    conversation = ConversationManager.from_dict(conv_data)
                meta_data = data.get("meta")
                if isinstance(meta_data, dict):
                    meta = SessionMeta.from_dict(meta_data)
            except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
                raise ValueError("session namespace could not be verified") from exc
        requested_context = str(context_id or "").strip()
        if meta is not None:
            stored_mode = str(meta.surface_mode or "chat").strip().lower()
            stored_context = str(meta.context_id or "").strip()
            if stored_mode != surface_mode or stored_context != requested_context:
                return None
        else:
            meta = SessionMeta(session_id=session_id)
            meta.surface_mode = surface_mode
            meta.context_id = requested_context or None
            if not await store._write_atomic(session_id, conversation, meta):
                raise OSError("session namespace reservation could not be persisted")
        return conversation, meta


__all__ = ["bind_surface_namespace"]
