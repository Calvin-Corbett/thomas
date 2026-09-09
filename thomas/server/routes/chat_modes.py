"""Legacy explicit-mode bridges for ``/api/chat``.

Natural-language turns are never split into casual/actionable paths here. See
``docs/CHAT_EXECUTION_MODEL.md`` for the model-owned execution contract.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web


async def maybe_handle_batch_mode(*args, **kwargs):
    """Bridge an explicitly selected batch mode when its handler is present."""
    try:
        from thomas.server.chat_batch_mode import maybe_execute_batch_chat as handle_batch_mode_chat
    except Exception:
        return None
    return await handle_batch_mode_chat(*args, **kwargs)


async def maybe_handle_swarm_mode(*args, **kwargs):
    """Bridge an explicitly selected swarm mode when its handler is present."""
    try:
        from thomas.server.routes.chat_swarm import handle_swarm_chat
    except Exception:
        return None
    return await handle_swarm_chat(*args, **kwargs)


async def maybe_handle_quick_casual_reply(
    *,
    request: web.Request,
    session_lock: Any,
    session: Any,
    text: str,
    mode: str,
    token_economy_meta: dict[str, Any],
    start_t: float,
    sid: str,
    deps: Any,
) -> web.StreamResponse | None:
    """Never intercept natural-language turns before the frontier model."""
    del request, session_lock, session, text, mode, token_economy_meta, start_t, sid, deps
    return None
