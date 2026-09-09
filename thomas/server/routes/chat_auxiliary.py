"""Non-conversational chat routes shared by the V2 web experience."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.agent.execution_plan import plan_from_payload
from thomas.server.app_keys import APP_SESSIONS, ChatSession

from .chat_aiohttp_helpers import _resolve_app_value
from .chat_plan_mode import build_plan_payload, serialize_web_slash_specs


def register_chat_auxiliary_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], Any],
) -> None:
    """Register plan-state and slash-command helpers without loading a chat engine."""

    async def api_chat_plan_state(request: web.Request) -> web.Response:
        require_api_access(request)
        session_id = str(request.match_info.get("session_id") or "").strip()
        if not session_id:
            raise web.HTTPBadRequest(text="missing session_id")
        sessions = _resolve_app_value(request.app, APP_SESSIONS, expected_type=dict, required=True)
        session = sessions.get(session_id)
        if not isinstance(session, ChatSession):
            raise web.HTTPNotFound(text="unknown session")
        plan = plan_from_payload(getattr(session, "active_plan", None))
        return web.json_response(
            {
                "session_id": session_id,
                "conversation_mode": str(getattr(session, "conversation_mode", "default") or "default"),
                "plan": build_plan_payload(plan) if plan is not None else None,
                "task_definition_status": str(getattr(session, "task_definition_status", "idle") or "idle"),
                "task_definition": getattr(session, "task_definition", None),
                "task_evaluation": getattr(session, "task_evaluation", None),
                "benchmark_session": getattr(session, "benchmark_session", None),
            }
        )

    async def api_chat_slash_commands(request: web.Request) -> web.Response:
        require_api_access(request)
        return web.json_response({"commands": serialize_web_slash_specs()})

    app.router.add_get("/api/chat/plan/{session_id}", api_chat_plan_state)
    app.router.add_get("/api/chat/slash-commands", api_chat_slash_commands)


__all__ = ["register_chat_auxiliary_routes"]
