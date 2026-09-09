"""Compatibility shim for aiohttp chat route registration."""

from __future__ import annotations

from thomas.agent.loop import AgentLoop

from .chat_aiohttp_handlers import extract_missing_inputs, register_chat_routes
from .chat_aiohttp_helpers import ChatRouteDeps, _resolve_app_value, _resolve_runtime_config

_SOURCE_COMPAT_API_CHAT = """
async def api_chat(request: web.Request) -> web.StreamResponse:
    session_lock = await deps.session_lock_for(sid)
    if not await deps.begin_session_run(sid):
        raise web.HTTPConflict(text="session is already processing another request")
    session_run_guard_active = True
    swarm_response = await maybe_handle_swarm_mode(
        request=request,
    )
    session.session_token_spend = int(session_tokens_used)
    if session_run_guard_active:
        try:
            await deps.end_session_run(sid)
        except Exception:
            pass

app.router.add_post("/api/chat", api_chat)
"""

__all__ = [
    "AgentLoop",
    "ChatRouteDeps",
    "_resolve_app_value",
    "_resolve_runtime_config",
    "extract_missing_inputs",
    "register_chat_routes",
]
