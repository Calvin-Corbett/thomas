"""Mode-specific handlers for /api/chat.

The dispatch-first architecture routes messages through dispatch.py first.
This module handles the "casual" path — short, low-intent messages where
Thomas replies directly without tools or heavy processing.

For actionable messages, dispatch.py routes to chat_dispatcher.py instead.
See docs/CHAT_EXECUTION_MODEL.md for the full picture.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)


async def maybe_handle_batch_mode(*args, **kwargs):
    """Compatibility batch-mode bridge for legacy source-contract checks."""
    try:
        from thomas.server.chat_batch_mode import maybe_execute_batch_chat as handle_batch_mode_chat
    except Exception:
        return None
    response = await handle_batch_mode_chat(*args, **kwargs)
    return response


async def maybe_handle_swarm_mode(*args, **kwargs):
    """Compatibility swarm-mode bridge for legacy source-contract checks."""
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
    """Handle casual/greeting messages with a fast direct reply.

    Returns a StreamResponse if handled, or None to fall through to
    the dispatch router and then the full agent loop.

    This is called BEFORE the dispatch router. It catches the simplest
    cases (pure greetings, thanks, filler) to avoid even running the
    dispatch classification.

    For anything more complex than a greeting, returns None and lets
    dispatch.py decide whether to dispatch or run inline.
    """
    # We intentionally return None here and let the dispatch router in
    # chat_aiohttp_part02.py handle the casual/actionable split.
    # The dispatch router has more sophisticated pattern matching and
    # also handles the Thomas personality for casual replies via the
    # normal agent loop with tools_policy="none".
    #
    # In the future, this function can be used for truly instant replies
    # that don't need any LLM call at all (e.g. "ping" → "pong").
    return None
