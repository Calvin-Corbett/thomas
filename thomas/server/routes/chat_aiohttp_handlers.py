"""Request handlers for chat aiohttp routes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from typing import Any

from aiohttp import web

from thomas.agent.execution_plan import plan_from_payload
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig
from thomas.models.chat_controls import resolve_ui_control_request
from thomas.server.app_keys import (
    APP_SESSIONS,
    ChatSession,
)
from thomas.server.chat_control_mode import handle_ui_control_chat

from .chat_aiohttp_helpers import (
    _SESSION_MSG_QUEUES,
    ChatRouteDeps,
    _as_bool,
    _clone_conversation_fallback,
    _create_parallel_fork_session,
    _resolve_app_value,
    _resolve_runtime_config,
)
from .chat_plan_mode import build_plan_payload, serialize_web_slash_specs

log = logging.getLogger(__name__)
_DEFAULT_AGENT_LOOP = AgentLoop
_DEFAULT_RESOLVE_UI_CONTROL_REQUEST = resolve_ui_control_request
_DEFAULT_HANDLE_UI_CONTROL_CHAT = handle_ui_control_chat


def register_chat_routes(
    app: web.Application,
    *,
    deps: ChatRouteDeps,
) -> None:
    """Register chat routes with the aiohttp application."""

    async def api_chat(request: web.Request) -> web.StreamResponse:
        # This endpoint can execute tool-calling flows, including file writes.
        # Keep it access-controlled (local loopback or remote token auth).
        deps.require_api_access(request)
        start_t = time.monotonic()
        payload = await deps.read_json(request)
        sid = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not sid:
            # Compatibility mode: allow single-shot callers that do not create
            # a session up front (Claude/OpenAI-style payloads).
            sid = secrets.token_urlsafe(18)
        request_sid = sid
        session_run_guard_active = False
        forked_sid: str | None = None
        fork_parent_sid: str | None = None
        fork_base_len = 0
        start_seed_events: list[dict[str, Any]] | None = None
        busy_strategy = str(payload.get("busy_strategy") or payload.get("when_busy") or "").strip().lower()
        if _as_bool(payload.get("parallel_fork")):
            busy_strategy = "fork"
        if _as_bool(payload.get("interrupt_if_busy")):
            busy_strategy = "interrupt"
        if not busy_strategy:
            busy_strategy = "interrupt"

        if not await deps.begin_session_run(sid):
            # Session has an active run.
            # Default behavior is Codex-style interrupt queueing so follow-up
            # user input can adapt the in-flight run. Explicit fork remains
            # available via busy_strategy/parallel_fork flags.
            msg_text = str(payload.get("text") or payload.get("message") or payload.get("prompt") or "").strip()
            wants_interrupt = busy_strategy in {"interrupt", "queue", "append", "continue", "interrupt_only"}
            wants_fork = busy_strategy in {"fork", "parallel", "branch"}

            if wants_interrupt:
                q = _SESSION_MSG_QUEUES.get(request_sid)
                if q is None:
                    raise web.HTTPConflict(
                        text="session is already processing another request (interrupt queue not ready)"
                    )
                if not msg_text:
                    raise web.HTTPBadRequest(text="message text is required when queueing interrupt input")
                try:
                    q.put_nowait(msg_text)
                except asyncio.QueueFull as queue_err:
                    log.warning("Interrupt queue full for session %s: %s", request_sid[:12], queue_err)
                    raise web.HTTPConflict(
                        text="session is already processing another request (interrupt queue is full)"
                    ) from queue_err

                deps.task_ledger_update(
                    request_sid,
                    status="in_progress",
                    missing_inputs=[],
                    last_progress="Received additional user instructions for active run.",
                    source="chat.interrupt_queued",
                    force_event=True,
                )
                log.info("Queued interrupt message for active session %s", request_sid[:12])
                return web.json_response(
                    {"ok": True, "queued": True, "detail": "Message queued for active run.", "session_id": request_sid},
                    status=202,
                )

            if not wants_fork:
                raise web.HTTPConflict(
                    text=f"session is already processing another request (busy_strategy={busy_strategy})"
                )

            try:
                sessions = _resolve_app_value(request.app, APP_SESSIONS, expected_type=dict, required=True)
                if sid not in sessions:
                    raise web.HTTPConflict(text="session is already processing another request")
                forked_sid, fork_base_len = _create_parallel_fork_session(sid, sessions)
                sid = forked_sid
                fork_parent_sid = request_sid
            except web.HTTPException:
                raise
            except Exception as fork_err:
                log.exception("Parallel chat fork failed (session=%s)", request_sid[:12])
                raise web.HTTPConflict(text="parallel chat fork failed") from fork_err
            start_seed_events = [
                {
                    "type": "parallel_fork",
                    "text": "Parallel chat branch started.",
                    "parent_session_id": request_sid[:12],
                    "fork_session_id": sid[:12],
                    "fork_base_len": fork_base_len,
                }
            ]
            if not await deps.begin_session_run(sid):
                _SESSION_MSG_QUEUES.pop(sid, None)
                with contextlib.suppress(Exception):
                    sessions.pop(sid, None)
                raise web.HTTPConflict(text="parallel session is already processing another request")
            session_run_guard_active = True
        else:
            if busy_strategy == "interrupt_only":
                with contextlib.suppress(Exception):
                    await deps.end_session_run(sid)
                raise web.HTTPConflict(text="session is idle; no active run to interrupt")
            session_run_guard_active = True

        try:
            return await _api_chat_inner(
                request=request,
                payload=payload,
                sid=sid,
                start_t=start_t,
                start_seed_events=start_seed_events,
            )
        except web.HTTPException:
            raise  # let aiohttp handle proper HTTP errors
        except Exception as exc:
            log.exception("[thomas] api_chat setup crashed (session=%s)", sid[:12])
            deps.task_ledger_update(
                request_sid,
                status="blocked",
                missing_inputs=extract_missing_inputs(str(exc)),
                last_progress=f"chat setup failed: {type(exc).__name__}: {exc}",
                source="chat.setup_error",
                force_event=True,
            )
            raise web.HTTPInternalServerError(text="chat setup failed") from exc
        finally:
            if session_run_guard_active:
                try:
                    await deps.end_session_run(sid)
                except Exception as guard_err:
                    log.warning("[thomas] session run guard cleanup failed: %s", guard_err)
                if fork_parent_sid is not None and forked_sid is not None:
                    try:
                        sessions = _resolve_app_value(request.app, APP_SESSIONS, expected_type=dict, required=True)
                        parent_session = sessions.get(fork_parent_sid)
                        fork_session = sessions.get(forked_sid)
                        if isinstance(parent_session, ChatSession) and isinstance(fork_session, ChatSession):
                            if not isinstance(parent_session.conversation, list):
                                parent_session.conversation = []
                            if isinstance(fork_session.conversation, list):
                                merge_start = max(0, int(fork_base_len))
                                if merge_start < len(fork_session.conversation):
                                    for msg in fork_session.conversation[merge_start:]:
                                        parent_session.conversation.append(_clone_conversation_fallback(msg))
                    except Exception as merge_err:
                        log.warning("Parallel fork merge failed: %s", merge_err)
                    finally:
                        sessions.pop(forked_sid, None)

    async def _api_chat_inner(
        request: web.Request,
        payload: dict[str, Any],
        sid: str,
        start_t: float,
        start_seed_events: list[dict[str, Any]] | None = None,
    ) -> web.StreamResponse:
        # Import streaming logic here to avoid circular imports
        from .chat_aiohttp_streaming import execute_chat_request

        session_lock = await deps.session_lock_for(sid)
        cfg: AppConfig = _resolve_runtime_config(request.app)
        fast_mode = _as_bool(payload.get("fast_mode"))

        return await execute_chat_request(
            request=request,
            payload=payload,
            sid=sid,
            start_t=start_t,
            start_seed_events=start_seed_events,
            session_lock=session_lock,
            cfg=cfg,
            fast_mode=fast_mode,
            deps=deps,
        )

    async def api_chat_plan_state(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        sid = str(request.match_info.get("session_id") or "").strip()
        if not sid:
            raise web.HTTPBadRequest(text="missing session_id")
        sessions = _resolve_app_value(request.app, APP_SESSIONS, expected_type=dict, required=True)
        session = sessions.get(sid)
        if not isinstance(session, ChatSession):
            raise web.HTTPNotFound(text="unknown session")
        plan = plan_from_payload(getattr(session, "active_plan", None))
        return web.json_response(
            {
                "session_id": sid,
                "conversation_mode": str(getattr(session, "conversation_mode", "default") or "default"),
                "plan": build_plan_payload(plan) if plan is not None else None,
                "task_definition_status": str(getattr(session, "task_definition_status", "idle") or "idle"),
                "task_definition": getattr(session, "task_definition", None),
                "task_evaluation": getattr(session, "task_evaluation", None),
                "benchmark_session": getattr(session, "benchmark_session", None),
            }
        )

    async def api_chat_slash_commands(request: web.Request) -> web.Response:
        deps.require_api_access(request)
        return web.json_response({"commands": serialize_web_slash_specs()})

    app.router.add_post("/api/chat", api_chat)
    app.router.add_get("/api/chat/plan/{session_id}", api_chat_plan_state)
    app.router.add_get("/api/chat/slash-commands", api_chat_slash_commands)


def extract_missing_inputs(error_text: str) -> list[str]:
    """Extract missing inputs from error text."""
    # Placeholder implementation - can be expanded based on error patterns
    if "missing" in error_text.lower():
        return ["unknown_input"]
    return []
