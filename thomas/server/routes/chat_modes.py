"""Mode-specific handlers for /api/chat."""

from __future__ import annotations

from typing import Any

from aiohttp import web


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
    """All messages must go through the LLM for real responses."""
    return None
