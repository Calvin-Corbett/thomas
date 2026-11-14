"""Turn-scoped inline memory capabilities with honest persistence receipts."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)


def memory_callbacks(memory_engine: Any, runtime_memory: Any, session_id: str) -> tuple[Any, Any]:
    """Expose memory tools only when an engine and permitted memory scope exist."""
    if memory_engine is None or not bool(getattr(runtime_memory, "enabled", True)):
        return None, None
    if not any(
        bool(getattr(runtime_memory, scope, True)) for scope in ("include_thread", "include_global", "include_profile")
    ):
        return None, None
    # Memory is THOMAS'S OWN capability — he stores/recalls inline, never via a task
    # (Calvin's law). Wire remember/recall callbacks straight to the memory engine.
    #
    # Explicit "remember X" facts MUST survive into future conversations, so they go to a
    # STABLE durable thread (not the ephemeral per-conversation session, which a new chat
    # never queries) with etype "user_fact" → role "user" — which makes them eligible for
    # profile extraction + global fact promotion. Recall then searches the current session,
    # this durable store, and the global/profile layer. Without this a remembered fact was
    # a session-scoped "system note" that vanished on the next chat (cross-session loss).
    _mem = memory_engine if bool(getattr(runtime_memory, "enabled", True)) else None
    _mem_thread = str(session_id or "default")
    _user_mem_thread = "user_memory"

    async def _remember_cb(*, text: str) -> bool:
        """Store a user-dictated fact durably. Returns True ONLY if actually saved."""
        if _mem is None:
            return False
        payload = str(text or "").strip()
        if not payload:
            return False
        include_thread = bool(getattr(runtime_memory, "include_thread", True))
        include_global = bool(getattr(runtime_memory, "include_global", True))
        include_profile = bool(getattr(runtime_memory, "include_profile", True))
        if not any((include_thread, include_global, include_profile)):
            return False
        target_thread = _user_mem_thread if include_global or include_profile else _mem_thread
        try:
            eid = _mem.add_event(
                thread=target_thread,
                etype="user_fact",
                text=payload,
                metadata={"source": "user_remember", "origin_session": _mem_thread},
            )
            if include_global:
                try:
                    _mem.auto_promote_event_memory(
                        thread_id=target_thread,
                        etype="user_fact",
                        text=payload,
                        source_episode_id=int(eid) if eid else None,
                    )
                except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                    log.debug("remember promotion failed", exc_info=True)
            return True
        # Same memory-store surface the promotion catch above names, plus
        # AttributeError for an engine missing add_event. Returning False is
        # load-bearing: reasoning.py only claims "Saved to your memory" when
        # this returns True, so a failure here must stay a False, not a raise.
        except (AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
            log.debug("remember failed", exc_info=True)
            return False

    async def _recall_cb(*, query: str) -> str:
        if _mem is None:
            return ""
        try:
            include_thread = bool(getattr(runtime_memory, "include_thread", True))
            include_global = bool(getattr(runtime_memory, "include_global", True))
            include_profile = bool(getattr(runtime_memory, "include_profile", True))
            if not any((include_thread, include_global, include_profile)):
                return ""
            setter = getattr(_mem, "set_thread_memory_policy", None)
            if callable(setter):
                setter(
                    _mem_thread,
                    include_thread=include_thread,
                    include_global=include_global,
                    include_profile=include_profile,
                    pins_only=bool(getattr(runtime_memory, "pins_only", False)),
                    max_results=int(getattr(runtime_memory, "retrieval_top_k", 5) or 5),
                    max_pack_tokens=int(getattr(runtime_memory, "context_budget", 1200) or 1200),
                )
            res = _mem.retrieve(query=str(query or ""), thread=_mem_thread)
            return str(getattr(res, "text", None) or res or "").strip()
        # Retrieval hits the same store as the write path above (OSError,
        # sqlite3.Error, RuntimeError), plus the int() coercions of the
        # runtime memory policy (TypeError/ValueError), a policy setter or
        # retrieve() the engine does not implement (AttributeError), and a
        # missing key in whatever it returns (LookupError). An empty string
        # is the honest answer for all of them.
        except (AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
            log.debug("recall failed", exc_info=True)
            return ""

    return _remember_cb, _recall_cb
