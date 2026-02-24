"""aiohttp route registration for session lifecycle (new, fork, import)."""

from __future__ import annotations

import json
import logging
import secrets as stdlib_secrets
from typing import Any, Awaitable, Callable, Dict, List, Optional

from aiohttp import web

from thomas.core.autonomy import clamp_autonomy_level
from thomas.core.config import AppConfig
from thomas.observability.task_ledger import derive_active_goal
from thomas.server.app_keys import (
    APP_CONFIG,
    APP_SESSIONS,
    APP_TASK_LEDGER,
    ChatSession,
)

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]
TaskLedgerUpdateFn = Callable[..., None]

log = logging.getLogger(__name__)


def register_sessions_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
    task_ledger_update: TaskLedgerUpdateFn,
) -> None:
    async def api_session_new(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        sid = stdlib_secrets.token_urlsafe(18)
        request.app[APP_SESSIONS][sid] = ChatSession(
            id=sid, conversation=[], profile=cfg.default_model, model_id=None, autonomy_level=3
        )
        task_ledger_update(
            sid,
            active_goal="",
            status="in_progress",
            missing_inputs=[],
            last_progress="Session created.",
            source="session.new",
            force_event=True,
        )
        return web.json_response({"session_id": sid})

    async def api_session_fork(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        src = str(payload.get("session_id") or "").strip()
        if not src or src not in request.app[APP_SESSIONS]:
            raise web.HTTPBadRequest(text="missing/invalid session_id")
        base: ChatSession = request.app[APP_SESSIONS][src]

        sid = stdlib_secrets.token_urlsafe(18)
        cloned = json.loads(json.dumps(base.conversation, ensure_ascii=False))
        request.app[APP_SESSIONS][sid] = ChatSession(
            id=sid,
            conversation=cloned,
            profile=base.profile,
            model_id=base.model_id,
            autonomy_level=clamp_autonomy_level(getattr(base, "autonomy_level", 3), default=3),
        )
        copied_state = None
        ledger = request.app.get(APP_TASK_LEDGER)
        if ledger is not None:
            try:
                copied_state = ledger.get_current(src)
            except Exception as e:
                log.debug("Task ledger read failed while forking session: %s", e)
        if copied_state is not None:
            task_ledger_update(
                sid,
                active_goal=copied_state.active_goal,
                status=copied_state.status,
                missing_inputs=copied_state.missing_inputs,
                last_progress="Session forked.",
                source="session.fork",
                force_event=True,
            )
        else:
            task_ledger_update(
                sid,
                active_goal="",
                status="in_progress",
                missing_inputs=[],
                last_progress="Session forked.",
                source="session.fork",
                force_event=True,
            )
        return web.json_response({"session_id": sid, "forked_from": src})

    async def api_session_import(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        payload = await read_json(request)

        profile = str(payload.get("profile") or payload.get("model") or cfg.default_model).strip()
        if profile not in cfg.models:
            # Graceful fallback: use default model or first available
            _fb = cfg.default_model
            if _fb not in cfg.models and cfg.models:
                _fb = next(iter(cfg.models))
            if _fb in cfg.models:
                log.warning("Session import: unknown profile '%s', falling back to '%s'", profile, _fb)
                profile = _fb
            else:
                raise web.HTTPBadRequest(text=f"unknown profile: {profile} (no models configured)")

        model_id = payload.get("model_id")
        if not (isinstance(model_id, str) and model_id.strip()):
            model_id = None
        else:
            model_id = model_id.strip()
        autonomy_level = clamp_autonomy_level(payload.get("autonomy_level", 3), default=3)

        raw_conv = payload.get("conversation") or []
        if not isinstance(raw_conv, list):
            raise web.HTTPBadRequest(text="conversation must be a list")
        if len(raw_conv) > 250:
            raise web.HTTPBadRequest(text="conversation too long")

        conversation: List[Dict[str, Any]] = []
        for m in raw_conv:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "").strip()
            if role not in ("user", "assistant"):
                continue
            content = m.get("content")
            if not isinstance(content, str):
                continue
            if len(content) > 120_000:
                content = content[:120_000] + "\n... (truncated)"
            conversation.append({"role": role, "content": content})

        sid = stdlib_secrets.token_urlsafe(18)
        request.app[APP_SESSIONS][sid] = ChatSession(
            id=sid,
            conversation=conversation,
            profile=profile,
            model_id=model_id,
            autonomy_level=autonomy_level,
        )
        last_user_message = ""
        for message in reversed(conversation):
            if str(message.get("role") or "") == "user":
                last_user_message = str(message.get("content") or "")
                break
        task_ledger_update(
            sid,
            active_goal=derive_active_goal(last_user_message, current_goal=""),
            status="in_progress",
            missing_inputs=[],
            last_progress="Session imported.",
            source="session.import",
            force_event=True,
        )
        return web.json_response({"session_id": sid})

    app.router.add_post("/api/session/new", api_session_new)
    app.router.add_post("/api/session/fork", api_session_fork)
    app.router.add_post("/api/session/import", api_session_import)
