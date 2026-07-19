"""Validation helpers for Chat and Work conversation namespaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChatSurfaceNamespace:
    mode: str
    context_id: str


def parse_chat_surface_namespace(payload: dict[str, Any]) -> ChatSurfaceNamespace:
    mode = str(payload.get("surface_mode") or payload.get("surfaceMode") or "chat").strip().lower()
    if mode not in {"chat", "work"}:
        raise ValueError("surface_mode must be chat or work")
    context_id = str(payload.get("context_id") or payload.get("contextId") or payload.get("work_job_id") or "").strip()
    if mode == "work" and not context_id:
        raise ValueError("context_id is required for Work sessions")
    if mode == "chat" and context_id:
        raise ValueError("context_id is only valid for Work sessions")
    return ChatSurfaceNamespace(mode=mode, context_id=context_id)


def session_namespace_matches(meta: Any, namespace: ChatSurfaceNamespace) -> bool:
    saved_mode = str(getattr(meta, "surface_mode", "chat") or "chat").strip().lower()
    saved_context = str(getattr(meta, "context_id", "") or "").strip()
    return saved_mode == namespace.mode and saved_context == namespace.context_id


__all__ = ["ChatSurfaceNamespace", "parse_chat_surface_namespace", "session_namespace_matches"]
