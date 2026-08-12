"""Validation helpers for Chat and Work conversation namespaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from thomas.chat.conversation import ConversationManager
from thomas.chat.session_namespace_binding import bind_surface_namespace


@dataclass(frozen=True)
class ChatSurfaceNamespace:
    mode: str
    context_id: str


WORKSPACE_CONTEXT_KEYS = frozenset(
    {
        "mission",
        "office",
        "app_builder",
        "my_stuff",
        "channels",
        "token_economy",
        "marketplace",
        "paper_trading",
        "settings",
    }
)

_WORKSPACE_CONTEXT_ALIASES = {
    "mission_control": "mission",
    "virtual_office": "office",
    "canvas": "app_builder",
    "library": "my_stuff",
    "my-stuff": "my_stuff",
    "token-economy": "token_economy",
}


def normalize_workspace_context_id(value: Any) -> str:
    """Return the one durable namespace used by workspace-resident chats."""

    raw = str(value or "").strip().lower()
    if not raw.startswith("workspace:"):
        raise ValueError("Workspace context_id must use the workspace:<route-mode> namespace")
    key = raw.removeprefix("workspace:").strip()
    key = _WORKSPACE_CONTEXT_ALIASES.get(key, key)
    if key not in WORKSPACE_CONTEXT_KEYS:
        raise ValueError("Unknown or unsupported workspace context_id")
    return f"workspace:{key}"


def parse_chat_surface_namespace(payload: dict[str, Any]) -> ChatSurfaceNamespace:
    mode = str(payload.get("surface_mode") or payload.get("surfaceMode") or "chat").strip().lower()
    if mode not in {"chat", "work", "workspace"}:
        raise ValueError("surface_mode must be chat, work, or workspace")
    context_id = str(payload.get("context_id") or payload.get("contextId") or payload.get("work_job_id") or "").strip()
    if mode == "work" and not context_id:
        raise ValueError("context_id is required for Work sessions")
    if mode == "workspace":
        context_id = normalize_workspace_context_id(context_id)
    elif mode == "chat" and context_id:
        raise ValueError("context_id is only valid for Work or workspace sessions")
    return ChatSurfaceNamespace(mode=mode, context_id=context_id)


def session_namespace_matches(meta: Any, namespace: ChatSurfaceNamespace) -> bool:
    saved_mode = str(getattr(meta, "surface_mode", "chat") or "chat").strip().lower()
    saved_context = str(getattr(meta, "context_id", "") or "").strip()
    return saved_mode == namespace.mode and saved_context == namespace.context_id


class SessionNamespaceBindError(RuntimeError):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


async def bind_chat_surface_session(
    session_store: Any,
    *,
    session_id: str,
    temporary: bool,
    namespace: ChatSurfaceNamespace,
) -> tuple[ConversationManager, Any]:
    if temporary:
        return ConversationManager(), None
    try:
        binding = await bind_surface_namespace(
            session_store,
            session_id,
            surface_mode=namespace.mode,
            context_id=namespace.context_id or None,
        )
    except (OSError, ValueError) as exc:
        raise SessionNamespaceBindError("session namespace could not be verified", 503) from exc
    if binding is None:
        raise SessionNamespaceBindError(
            "session namespace does not match the requested mode or context", 409
        )
    return binding


__all__ = [
    "ChatSurfaceNamespace",
    "SessionNamespaceBindError",
    "WORKSPACE_CONTEXT_KEYS",
    "bind_chat_surface_session",
    "normalize_workspace_context_id",
    "parse_chat_surface_namespace",
    "session_namespace_matches",
]
