"""aiohttp route registration for session lifecycle (new, fork, import)."""

from __future__ import annotations

import copy
import logging
import secrets as stdlib_secrets
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from thomas.core.autonomy import clamp_autonomy_level
from thomas.core.config import AppConfig
from thomas.marketplace.observability.task_ledger import derive_active_goal
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


def _clone_conversation_fallback(value: Any) -> Any:
    """Clone list/dict conversation data without relying on JSON serialization."""
    if isinstance(value, dict):
        return {k: _clone_conversation_fallback(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clone_conversation_fallback(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_clone_conversation_fallback(v) for v in value)
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


def register_sessions_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
    task_ledger_update: TaskLedgerUpdateFn,
) -> None:
    def _resolve_default_model() -> tuple[str, str]:
        try:
            from os import environ

            from thomas.core.model_resolution import resolve_effective_model
            from thomas.preferences.store import get_db_path

            resolved_profile, resolved_model_id = resolve_effective_model(
                app[APP_CONFIG],
                env_profile=str(environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
                user_id="default",
                db_path=get_db_path(),
            )
            if resolved_profile in app[APP_CONFIG].models:
                return resolved_profile, str(resolved_model_id or "")
        except Exception:
            pass
        cfg_local = app[APP_CONFIG]
        fallback = str(cfg_local.default_model or "").strip()
        if fallback not in cfg_local.models and cfg_local.models:
            fallback = next(iter(cfg_local.models))
        return fallback, ""

    async def api_session_new(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        default_profile, default_model_id = _resolve_default_model()
        sid = stdlib_secrets.token_urlsafe(18)
        if default_profile not in cfg.models:
            default_profile = str(cfg.default_model or "").strip()
        request.app[APP_SESSIONS][sid] = ChatSession(
            id=sid,
            conversation=[],
            profile=default_profile,
            model_id=(default_model_id or None),
            autonomy_level=3,
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
        try:
            cloned = copy.deepcopy(base.conversation)
        except (TypeError, ValueError, copy.Error, RecursionError) as e:
            log.warning("Session fork: deepcopy failed for %s, using safe fallback clone: %s", src, e)
            cloned = _clone_conversation_fallback(base.conversation)
        request.app[APP_SESSIONS][sid] = ChatSession(
            id=sid,
            conversation=cloned,
            profile=base.profile,
            model_id=base.model_id,
            autonomy_level=clamp_autonomy_level(getattr(base, "autonomy_level", 3), default=3),
            conversation_mode=str(getattr(base, "conversation_mode", "default") or "default"),
            active_plan=copy.deepcopy(getattr(base, "active_plan", None)),
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
        default_profile, default_model_id = _resolve_default_model()

        explicit_model_alias_requested = "model" in payload and str(payload.get("model")).strip()
        profile = str(payload.get("profile") or payload.get("model") or "").strip()
        if profile not in cfg.models:
            if explicit_model_alias_requested:
                raise web.HTTPBadRequest(text=f"unknown profile: {profile}")
            # Graceful fallback: use user-configured default or first available
            if default_profile and default_profile in cfg.models:
                _fb = default_profile
            else:
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

        conversation: list[dict[str, Any]] = []
        for m in raw_conv:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "").strip()
            if role not in ("user", "assistant"):
                continue
            content = m.get("content")
            if not isinstance(content, str):
                continue
            content = content.strip()
            if not content:
                continue
            if len(content) > 120_000:
                content = content[:120_000] + "\n... (truncated)"
            conversation.append({"role": role, "content": content})

        sid = stdlib_secrets.token_urlsafe(18)
        if not profile and not model_id and default_profile in cfg.models:
            profile = default_profile
        if (not model_id) and profile == default_profile and default_model_id:
            model_id = default_model_id
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
