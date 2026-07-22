"""Route handlers and final app setup for Thomas server."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import mimetypes
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.core.config import AppConfig
from thomas.server.app_keys import (
    APP_ENGINE_MANAGER,
    APP_MEMORY,
    APP_MUTATING_ROUTE_POLICY_SNAPSHOT,
    APP_RESTART_REQUESTED,
    APP_RUN_STORE_ENABLED,
    APP_RUN_STORE_MODULE,
    APP_RUNTIME_GUARD_TASK,
    APP_SESSIONS,
    APP_SHUTDOWN_EVENT,
    APP_TASK_LEDGER,
    APP_TOOLS,
    ChatSession,
)
from thomas.server.routes.chat_surface_namespace import normalize_workspace_context_id
from thomas.tools.registry import ToolRegistry

from .app_runtime_guard import _runtime_guard_loop

if TYPE_CHECKING:
    from aiohttp import web

log = logging.getLogger(__name__)
_RUN_STORE_JANITOR_INTERVAL_SECONDS = 120
_RUN_STORE_STALE_IDLE_SECONDS = 10 * 60


def _v2_sessions_as_chats(
    sessions_dir: Path,
    *,
    limit: int = 300,
    surface_mode: str = "",
    context_id: str = "",
) -> list[dict[str, Any]]:
    """Convert the LIVE v2 session store (``.thomas/sessions_v2/chat_*.json`` — where
    every chat conducted through /api/v2/chat is saved) into the sidebar's chat-list
    schema. GET /api/chats historically read ONLY the legacy ``.thomas/chats`` directory
    (written by the old SPA's PUT /api/chats), which the current chat UI never writes —
    so brand-new chats never showed up in Recent (no entry, no date). This bridges the
    two so real, current chats appear with their dates. (chat history fix, 2026-06-28)"""
    out: list[dict[str, Any]] = []
    try:
        files = list(sessions_dir.glob("chat_*.json"))
    except OSError:
        return out

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    files.sort(key=_mtime, reverse=True)
    result_limit = max(1, int(limit))
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        sid = str(data.get("session_id") or "").strip()
        if not sid:
            continue
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        stored_surface = str(meta.get("surface_mode") or "chat").strip().lower()
        stored_context = str(meta.get("context_id") or "").strip()
        if surface_mode and stored_surface != surface_mode:
            continue
        if context_id and stored_context != context_id:
            continue
        conv = data.get("conversation") if isinstance(data.get("conversation"), dict) else {}
        msgs: list[dict[str, Any]] = []
        for msg in conv.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "")
            content = msg.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                msgs.append({"role": role, "content": content})
        if not msgs:
            continue  # empty / system-only session — nothing to show in the sidebar
        first_user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        title = (first_user.strip().splitlines()[0][:60] if first_user.strip() else "New chat") or "New chat"
        saved_at = data.get("saved_at")
        updated_ms = int(float(saved_at) * 1000) if isinstance(saved_at, (int, float)) else int(_mtime(path) * 1000)
        out.append(
            {
                "id": sid,
                "sessionId": sid,
                "title": title,
                "surfaceMode": stored_surface,
                "contextId": stored_context,
                "model": str(meta.get("model_id") or ""),
                "messages": msgs,
                "createdAt": updated_ms,
                "updatedAt": updated_ms,
                "pinned": False,
            }
        )
        if len(out) >= result_limit:
            break
    return out


def _setup_routes_and_handlers(
    app: web.Application,
    config: AppConfig,
    web_dir: Path,
    chat_store_dir: Path,
    chat_store_lock: asyncio.Lock,
    # Functions defined in create_app that we need to reference
    locals_dict: dict[str, Any] | None = None,
) -> None:
    """Setup all route handlers and finalize the app.

    This function is called at the end of create_app to register routes
    and final configuration after all middleware setup is complete.

    The locals_dict parameter should contain references to functions
    defined inside create_app (they're nested functions that we can't import).
    """
    from aiohttp import web

    if locals_dict is None:
        locals_dict = {}

    # Extract function references from locals
    _require_api_access = locals_dict.get("_require_api_access")
    _require_loopback = locals_dict.get("_require_loopback")
    _is_json_content_type = locals_dict.get("_is_json_content_type")
    _read_json = locals_dict.get("_read_json")
    _sanitize_chat_payload = locals_dict.get("_sanitize_chat_payload")
    _save_chat_to_disk = locals_dict.get("_save_chat_to_disk")
    _delete_chat_from_disk = locals_dict.get("_delete_chat_from_disk")
    _load_all_chats_from_disk = locals_dict.get("_load_all_chats_from_disk")
    _session_lock_for = locals_dict.get("_session_lock_for")
    _begin_session_run = locals_dict.get("_begin_session_run")
    _end_session_run = locals_dict.get("_end_session_run")
    _task_ledger_update = locals_dict.get("_task_ledger_update")
    _model_cfg_with_secrets = locals_dict.get("_model_cfg_with_secrets")
    _failover_cfgs_with_secrets = locals_dict.get("_failover_cfgs_with_secrets")
    _resolve_natural_model_switch_request = locals_dict.get("_resolve_natural_model_switch_request")
    _chat_file_for = locals_dict.get("_chat_file_for")
    _read_chat_from_disk = locals_dict.get("_read_chat_from_disk")
    _build_tools = locals_dict.get("_build_tools")
    _web_build_fingerprint = locals_dict.get("_web_build_fingerprint")
    index = locals_dict.get("index")
    classic = locals_dict.get("classic")
    settings = locals_dict.get("settings")
    companion = locals_dict.get("companion")
    landing = locals_dict.get("landing")

    # Task ledger routes
    async def api_task_ledger_current(request: web.Request) -> web.Response:
        """Return current task ledger snapshot for a session (or latest session)."""
        _require_api_access(request)
        ledger = app.get(APP_TASK_LEDGER)
        if not ledger:
            raise web.HTTPNotFound(text="task ledger unavailable")

        session_id = str(request.query.get("session_id", "")).strip()
        snapshot_obj = ledger.get_current(session_id) if session_id else ledger.get_latest()
        snapshot = snapshot_obj.to_dict() if snapshot_obj and hasattr(snapshot_obj, "to_dict") else None
        resolved_session_id = str(
            session_id or getattr(snapshot_obj, "session_id", "") or (snapshot or {}).get("session_id") or ""
        ).strip()
        sessions = app.get(APP_SESSIONS, {})
        session_obj = sessions.get(resolved_session_id) if isinstance(sessions, dict) and resolved_session_id else None
        task_definition = (
            dict(getattr(session_obj, "task_definition", {}) or {}) if isinstance(session_obj, ChatSession) else None
        )
        task_evaluation = (
            dict(getattr(session_obj, "task_evaluation", {}) or {}) if isinstance(session_obj, ChatSession) else None
        )
        benchmark_session = (
            dict(getattr(session_obj, "benchmark_session", {}) or {}) if isinstance(session_obj, ChatSession) else None
        )
        task_definition_status = (
            str(getattr(session_obj, "task_definition_status", "idle") or "idle")
            if isinstance(session_obj, ChatSession)
            else "idle"
        )
        if isinstance(snapshot, dict):
            fallback_user_text = (
                str(getattr(session_obj, "last_user_message", "") or "") if isinstance(session_obj, ChatSession) else ""
            )
            fallback_assistant_text = (
                str(getattr(session_obj, "last_assistant_message", "") or "")
                if isinstance(session_obj, ChatSession)
                else ""
            )
            if isinstance(session_obj, ChatSession) and isinstance(session_obj.conversation, list):
                for message in reversed(session_obj.conversation):
                    if not fallback_assistant_text and str(message.get("role") or "") == "assistant":
                        fallback_assistant_text = str(message.get("content") or "")
                    if not fallback_user_text and str(message.get("role") or "") == "user":
                        fallback_user_text = str(message.get("content") or "")
                    if fallback_user_text and fallback_assistant_text:
                        break
            try:
                from thomas.marketplace.observability.task_ledger import derive_active_goal, extract_missing_inputs

                if not str(snapshot.get("active_goal") or "").strip() and fallback_user_text:
                    snapshot["active_goal"] = derive_active_goal(fallback_user_text, current_goal="")
                progress_text = str(snapshot.get("last_progress") or fallback_assistant_text or "").strip()
                inferred_missing = extract_missing_inputs(progress_text)
                if inferred_missing and not list(snapshot.get("missing_inputs") or []):
                    snapshot["status"] = "blocked"
                    snapshot["missing_inputs"] = inferred_missing
                    if not str(snapshot.get("last_progress") or "").strip():
                        snapshot["last_progress"] = progress_text
            except Exception:
                pass
        return web.json_response(
            {
                "ok": True,
                "session_id": resolved_session_id,
                "state": snapshot,
                "snapshot": snapshot,
                "task_definition_status": task_definition_status,
                "task_definition": task_definition,
                "task_evaluation": task_evaluation,
                "benchmark_session": benchmark_session,
            }
        )

    async def api_task_ledger_history(request: web.Request) -> web.Response:
        """Return task ledger history for a session (or latest session)."""
        _require_api_access(request)
        ledger = app.get(APP_TASK_LEDGER)
        if not ledger:
            raise web.HTTPNotFound(text="task ledger unavailable")

        session_id = str(request.query.get("session_id", "")).strip()
        if not session_id:
            latest = ledger.get_latest()
            session_id = str(getattr(latest, "session_id", "") or "").strip()
        try:
            limit = max(1, min(int(str(request.query.get("limit", "50") or "50")), 200))
        except (TypeError, ValueError) as e:
            raise web.HTTPBadRequest(text="invalid limit") from e

        history = ledger.get_history(session_id, limit=limit) if session_id else []
        return web.json_response(
            {
                "ok": True,
                "session_id": session_id,
                "events": history,
                "history": history,
            }
        )

    async def api_security_mutating_routes(request: web.Request) -> web.Response:
        """Return security policy snapshot for mutating routes."""
        _require_api_access(request)
        snapshot = app.get(APP_MUTATING_ROUTE_POLICY_SNAPSHOT, {})
        return web.json_response(snapshot)

    async def api_engines(request: web.Request) -> web.Response:
        """Return engine manager status and results."""
        _require_api_access(request)
        engine_manager = app.get(APP_ENGINE_MANAGER)
        if not engine_manager:
            return web.json_response({"status": "unavailable"})
        return web.json_response({"status": "ok", "engines": engine_manager.status()})

    async def api_tools(request: web.Request) -> web.Response:
        """List all registered tools."""
        _require_api_access(request)
        registry: ToolRegistry | None = app.get(APP_TOOLS)
        if not registry:
            return web.json_response({"tools": [], "count": 0})

        tools_list = []
        for tool in registry.list_tools():
            parameters = getattr(tool, "parameters", {})
            if not isinstance(parameters, dict):
                parameters = {}
            tool_dict = {
                "id": getattr(tool, "name", ""),
                "name": getattr(tool, "name", ""),
                "description": getattr(tool, "description", ""),
                "category": getattr(tool, "category", ""),
                "status": "active",
                "params": parameters,
                "parameters": parameters,
            }
            tools_list.append(tool_dict)
        return web.json_response({"tools": tools_list, "count": len(tools_list)})

    # Chat storage routes
    async def api_chats(request: web.Request) -> web.Response:
        """List all chats from disk storage.

        Merges the legacy ``.thomas/chats`` store (old SPA's PUT /api/chats) with the
        LIVE ``.thomas/sessions_v2`` store (every chat from the current /api/v2/chat
        flow). Before this merge the sidebar only saw the legacy store, so new chats
        never appeared in Recent. Dedup by id; the newer ``updatedAt`` wins.
        """
        _require_api_access(request)
        requested_surface = str(request.query.get("mode") or "").strip().lower()
        requested_context = str(request.query.get("context_id") or "").strip()
        if requested_surface and requested_surface not in {"chat", "work", "workspace"}:
            raise web.HTTPBadRequest(text="mode must be chat, work, or workspace")
        if requested_surface == "workspace":
            if not requested_context:
                raise web.HTTPBadRequest(text="context_id is required for workspace histories")
            try:
                requested_context = normalize_workspace_context_id(requested_context)
            except ValueError as exc:
                raise web.HTTPBadRequest(text=str(exc)) from exc
        legacy = await _load_all_chats_from_disk()
        sessions_dir = config.memory.root_path / ".thomas" / "sessions_v2"
        live = await asyncio.to_thread(
            _v2_sessions_as_chats,
            sessions_dir,
            surface_mode=requested_surface,
            context_id=requested_context,
        )

        def _ms(chat: dict[str, Any]) -> int:
            try:
                return int(chat.get("updatedAt") or 0)
            except (TypeError, ValueError):
                return 0

        by_id: dict[str, dict[str, Any]] = {}
        for chat in [*legacy, *live]:
            cid = str(chat.get("id") or chat.get("sessionId") or "").strip()
            if not cid:
                continue
            surface = str(chat.get("surfaceMode") or chat.get("surface_mode") or "chat").strip().lower()
            context_id = str(chat.get("contextId") or chat.get("context_id") or "").strip()
            if requested_surface and surface != requested_surface:
                continue
            if requested_context and context_id != requested_context:
                continue
            # Preserve the exact legacy response contract for callers that never
            # opted into namespaced histories. V2 rows already carry these keys.
            row = dict(chat)
            if "surfaceMode" in chat or "surface_mode" in chat:
                row["surfaceMode"] = surface
            if "contextId" in chat or "context_id" in chat:
                row["contextId"] = context_id
            prev = by_id.get(cid)
            if prev is None or _ms(row) >= _ms(prev):
                by_id[cid] = row
        chats = sorted(by_id.values(), key=_ms, reverse=True)
        return web.json_response({"chats": chats})

    async def api_chat_put(request: web.Request) -> web.Response:
        """Save or update a chat."""
        _require_api_access(request)
        if not _is_json_content_type(request):
            raise web.HTTPBadRequest(text="Content-Type must be application/json")

        payload = await _read_json(request)
        chat = _sanitize_chat_payload(payload)

        # If the URL specifies a chat_id, it must match the payload id (prevents
        # accidental cross-chat overwrites). Returns 400 on mismatch.
        url_chat_id = request.match_info.get("chat_id", "").strip()
        payload_chat_id = str(chat.get("id") or "").strip()
        if url_chat_id and payload_chat_id and url_chat_id != payload_chat_id:
            raise web.HTTPBadRequest(text=f"chat id mismatch: URL='{url_chat_id}' payload='{payload_chat_id}'")

        await _save_chat_to_disk(chat)
        return web.json_response({"ok": True, "chat": chat})

    async def api_chat_delete(request: web.Request) -> web.Response:
        """Delete a chat."""
        _require_api_access(request)
        chat_id = request.match_info.get("chat_id", "")
        if not chat_id:
            raise web.HTTPBadRequest(text="missing chat_id")

        deleted = await _delete_chat_from_disk(chat_id)
        if not deleted:
            raise web.HTTPNotFound(text=f"chat {chat_id} not found")
        # Tests expect 200 with a small JSON ack (was 204 no-content).
        return web.json_response({"ok": True, "deleted": chat_id})

    run_store_janitor_task: asyncio.Task | None = None

    async def _run_store_janitor(app_ref: web.Application) -> None:
        while True:
            await asyncio.sleep(_RUN_STORE_JANITOR_INTERVAL_SECONDS)
            if not bool(app_ref.get(APP_RUN_STORE_ENABLED)):
                continue
            run_store_mod = app_ref.get(APP_RUN_STORE_MODULE)
            if run_store_mod is None:
                continue
            try:
                reconciled = int(
                    run_store_mod.reconcile_stale_runs(
                        idle_seconds=_RUN_STORE_STALE_IDLE_SECONDS,
                        reason="stale run janitor reconciliation",
                    )
                    or 0
                )
            except Exception as janitor_exc:
                log.debug("Run store janitor skipped: %s", janitor_exc)
                continue
            if reconciled:
                log.warning("Run store janitor reconciled %d stale runs", reconciled)

    # Startup and cleanup
    async def on_startup(app_ref: web.Application) -> None:
        """App startup handler."""
        nonlocal run_store_janitor_task
        guard_task = asyncio.create_task(_runtime_guard_loop(app_ref))
        app_ref[APP_RUNTIME_GUARD_TASK] = guard_task
        if bool(app_ref.get(APP_RUN_STORE_ENABLED)) and app_ref.get(APP_RUN_STORE_MODULE) is not None:
            run_store_mod = app_ref.get(APP_RUN_STORE_MODULE)
            try:
                reconciled = int(
                    run_store_mod.reconcile_orphaned_runs(
                        started_before=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        reason="server startup reconciliation",
                    )
                    or 0
                )
            except Exception as startup_exc:
                log.debug("Run store startup reconciliation skipped: %s", startup_exc)
            else:
                if reconciled:
                    log.warning("Run store reconciled %d orphaned runs on startup", reconciled)
            run_store_janitor_task = asyncio.create_task(_run_store_janitor(app_ref))

        # Branch-sprawl maintenance: places/lifts the consolidation hold on a
        # cadence so sprawl is caught without anyone remembering to look.
        try:
            from thomas.server.consolidation_maintenance import consolidation_maintenance_loop

            app_ref["consolidation_maintenance_task"] = asyncio.create_task(consolidation_maintenance_loop(app_ref))
        except (ImportError, ModuleNotFoundError, RuntimeError, TypeError) as consolidation_exc:
            log.debug("Consolidation maintenance not started: %s", consolidation_exc)

    async def on_cleanup(app_ref: web.Application) -> None:
        """App cleanup handler."""
        nonlocal run_store_janitor_task
        guard_task = app_ref.get(APP_RUNTIME_GUARD_TASK)
        if guard_task:
            guard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await guard_task
        consolidation_task = app_ref.get("consolidation_maintenance_task")
        if consolidation_task:
            consolidation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consolidation_task
        if run_store_janitor_task is not None:
            run_store_janitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_store_janitor_task
            run_store_janitor_task = None
        run_store_mod = app_ref.get(APP_RUN_STORE_MODULE)
        shutdown_runs = getattr(run_store_mod, "shutdown", None) if run_store_mod is not None else None
        if callable(shutdown_runs):
            with contextlib.suppress(Exception):
                shutdown_runs(close_timeout=5.0)

        memory_engine = app_ref.get(APP_MEMORY)
        close_memory = getattr(memory_engine, "close", None)
        if callable(close_memory):
            with contextlib.suppress(Exception):
                close_memory()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    # Gateway routing
    def _register_gateway_routes(app_ref: web.Application, config: AppConfig) -> None:
        """Register gateway routes if available."""
        try:
            from thomas.server.routes.gateway import register_gateway_routes

            register_gateway_routes(app_ref, config)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.debug("Gateway routes unavailable: %s", e)

    _register_gateway_routes(app, config)

    def _register_frontier_surfaces(app_ref: web.Application, config: AppConfig) -> None:
        """Register the frontier capability surfaces (agent-ops panels)."""
        try:
            from thomas.server.routes.frontier_surfaces import register_frontier_surface_routes

            register_frontier_surface_routes(app_ref, config)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.debug("Frontier surfaces unavailable: %s", e)

    _register_frontier_surfaces(app, config)

    def _register_engine_actions_routes(app_ref: web.Application) -> None:
        """Register the user-triggered manual engine-actions endpoint."""
        if not callable(_require_api_access) or not callable(_read_json):
            log.warning("Engine actions route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.engine_actions_aiohttp import register_engine_actions_routes

            register_engine_actions_routes(
                app_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Engine actions routes unavailable: %s", e)

    _register_engine_actions_routes(app)

    def _register_chat_and_session_routes(app_ref: web.Application, cfg_ref: AppConfig) -> None:
        """Register the live session/chat route bundles when their deps are available."""
        _ = cfg_ref
        if not all(callable(dep) for dep in (_require_api_access, _read_json, _task_ledger_update)):
            log.warning("Chat/session route registration skipped: missing runtime dependencies")
            return

        try:
            from thomas.server.routes.sessions_aiohttp import register_sessions_routes

            def _task_ledger_update_compat(
                session_id: str,
                *,
                active_goal: Any = None,
                status: Any = None,
                missing_inputs: Any = None,
                last_progress: Any = None,
                source: str = "",
                force_event: bool = False,
            ) -> None:
                try:
                    ledger = app_ref.get(APP_TASK_LEDGER)
                    if ledger and hasattr(ledger, "update"):
                        ledger.update(
                            session_id,
                            active_goal=active_goal,
                            status=status,
                            missing_inputs=missing_inputs,
                            last_progress=last_progress,
                            source=source,
                            force_event=force_event,
                        )
                        return
                except Exception as e:
                    log.debug("Task ledger compat update failed: %s", e)
                _task_ledger_update(session_id, active_goal, status or "in_progress")

            register_sessions_routes(
                app_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
                task_ledger_update=_task_ledger_update_compat,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Session routes unavailable: %s", e)

        # Session lifecycle is a core dependency for Chat, Work onboarding, and
        # several automation surfaces.  Keep it registered even when an optional
        # chat helper (for example CLI slash-command presentation) is unavailable.
        try:
            from thomas.server.routes.chat_auxiliary import register_chat_auxiliary_routes

            register_chat_auxiliary_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Chat auxiliary routes unavailable: %s", e)

    _register_chat_and_session_routes(app, config)

    def _register_models_routes(app_ref: web.Application, cfg_ref: AppConfig) -> None:
        """Register model/profile routes used by the web app and boot probes."""
        if not callable(_require_api_access) or not callable(_model_cfg_with_secrets):
            log.warning("Models route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.models_aiohttp import register_models_routes

            def _model_cfg_for_profile(profile: str) -> Any:
                model_cfg = cfg_ref.models.get(profile)
                if model_cfg is None:
                    raise KeyError(profile)
                return _model_cfg_with_secrets(cfg_ref, profile, model_cfg)

            register_models_routes(
                app_ref,
                require_api_access=_require_api_access,
                model_cfg_with_secrets=_model_cfg_for_profile,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Models routes unavailable: %s", e)

    _register_models_routes(app, config)

    def _register_setup_routes(app_ref: web.Application) -> None:
        """Register setup and local-runtime onboarding routes."""
        if not callable(_require_api_access) or not callable(_require_loopback) or not callable(_read_json):
            log.warning("Setup route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.setup_aiohttp import register_setup_routes

            register_setup_routes(
                app_ref,
                require_api_access=_require_api_access,
                require_loopback=_require_loopback,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Setup routes unavailable: %s", e)

    _register_setup_routes(app)

    def _register_third_party_access_routes(app_ref: web.Application) -> None:
        """Register loopback-only security controls for third-party agent access."""
        if not callable(_require_api_access) or not callable(_require_loopback) or not callable(_read_json):
            log.warning("Third-party access route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.third_party_agent_access_aiohttp import register_third_party_agent_access_routes

            register_third_party_agent_access_routes(
                app_ref,
                require_api_access=_require_api_access,
                require_loopback=_require_loopback,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Third-party access routes unavailable: %s", e)

    _register_third_party_access_routes(app)

    def _register_preferences_and_memory_routes(app_ref: web.Application) -> None:
        """Register preferences, onboarding, and memory APIs once runtime guards exist."""
        if not callable(_require_api_access):
            log.warning("Preferences/memory route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.memory_aiohttp import register_memory_routes
            from thomas.server.routes.onboarding_aiohttp import register_onboarding_routes
            from thomas.server.routes.preferences_aiohttp import register_preferences_routes

            register_preferences_routes(
                app_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
            )
            register_onboarding_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
            register_memory_routes(
                app_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Preferences/memory routes unavailable: %s", e)

    _register_preferences_and_memory_routes(app)

    def _register_office_state_routes(app_ref: web.Application) -> None:
        if not callable(_require_api_access) or not callable(_read_json):
            log.warning("Office state route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.office_state_aiohttp import register_office_state_routes

            register_office_state_routes(
                app_ref,
                root=config.memory.root_path,
                require_api_access=_require_api_access,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as exc:
            log.warning("Office state routes unavailable: %s", exc)

    _register_office_state_routes(app)

    def _register_search_routes(app_ref: web.Application) -> None:
        """Register conversation search APIs used by web search surfaces."""
        if not callable(_require_api_access):
            log.warning("Search route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.search import register_search_routes

            register_search_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Search routes unavailable: %s", e)

    _register_search_routes(app)

    def _register_canvas_studio_routes(app_ref: web.Application) -> None:
        """Register the UI Studio design-canvas API (/api/canvas/*).

        The client surface is the UI Editor's coordinate canvas
        (runtime/048_ui_studio_canvas.js). These routes power the AI Template
        (prompt -> layout) and sketch-import (photo -> layout) helpers; the
        core draw -> code path is client-side, so the routes are inert without
        a caller and safe to register additively.
        """
        if not callable(_require_api_access):
            log.warning("UI Studio route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.canvas_studio_routes import register_canvas_studio_routes

            register_canvas_studio_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("UI Studio routes unavailable: %s", e)

    _register_canvas_studio_routes(app)

    def _register_discord_channels_routes(app_ref: web.Application, cfg_ref: AppConfig) -> None:
        """Register Thomas-owned Discord bridge lifecycle and history APIs."""
        if not callable(_require_api_access) or not callable(_read_json):
            log.warning("Discord channels route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.discord_channels_aiohttp import register_discord_channels_routes

            register_discord_channels_routes(
                app_ref,
                config=cfg_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Discord channels routes unavailable: %s", e)

    _register_discord_channels_routes(app, config)

    def _register_secrets_routes(app_ref: web.Application) -> None:
        """Register API-key and secret rotation APIs."""
        if not callable(_require_api_access) or not callable(_read_json):
            log.warning("Secrets route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.secrets_aiohttp import register_secrets_routes

            register_secrets_routes(
                app_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Secrets routes unavailable: %s", e)

    _register_secrets_routes(app)

    def _register_webhooks_routes(app_ref: web.Application) -> None:
        """Register webhook management and public receive routes.

        In remote-access mode, signature enforcement defaults to ON so that an
        operator who forgets to set the provider secret gets a deterministic 503
        instead of a 500. Local mode keeps the historical opt-in behavior.
        """
        if not callable(_require_api_access):
            log.warning("Webhook route registration skipped: missing API access guard")
            return
        try:
            from thomas.server.routes.webhooks_aiohttp import register_webhooks_routes

            mode = str(getattr(getattr(config, "server", None), "access_mode", "local") or "local").strip().lower()
            sig_default = True if mode == "remote" else None
            register_webhooks_routes(
                app_ref,
                require_api_access=_require_api_access,
                signature_enforcement_default=sig_default,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Webhook routes unavailable: %s", e)

    _register_webhooks_routes(app)

    def _register_companion_routes(app_ref: web.Application, cfg_ref: AppConfig) -> None:
        """Register companion-app management API routes (/api/companion/v1/*)."""
        if not callable(_require_api_access) or not callable(_read_json):
            log.warning("Companion route registration skipped: missing dependencies")
            return
        try:
            from thomas.server.routes.companion_aiohttp import register_companion_routes

            register_companion_routes(
                app_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
                config=cfg_ref,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Companion routes unavailable: %s", e)

    _register_companion_routes(app, config)

    def _register_asset_studio_routes(app_ref: web.Application) -> None:
        """Register Asset Studio API routes (/api/asset-studio/v1/*).

        Same "designed but never wired" pattern as goals/spend/companion that
        was caught earlier in this recovery arc (Pattern 1 in the bible).
        ``register_asset_studio_routes`` existed but no caller invoked it,
        so every test_asset_studio_routes assertion returned 404.
        """
        if not callable(_require_api_access) or not callable(_read_json):
            log.warning("Asset Studio route registration skipped: missing dependencies")
            return
        try:
            from thomas.server.routes.asset_studio_aiohttp import register_asset_studio_routes

            register_asset_studio_routes(
                app_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Asset Studio routes unavailable: %s", e)

    _register_asset_studio_routes(app)

    def _register_goals_routes(app_ref: web.Application) -> None:
        """Register /api/goals/* routes."""
        if not callable(_require_api_access) or not callable(_read_json):
            log.warning("Goals route registration skipped: missing dependencies")
            return
        try:
            from thomas.server.routes.goals import register_goals_routes

            register_goals_routes(
                app_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Goals routes unavailable: %s", e)

    _register_goals_routes(app)

    def _register_spend_routes(app_ref: web.Application) -> None:
        """Register /api/spend/* routes."""
        if not callable(_require_api_access):
            log.warning("Spend route registration skipped: missing API access guard")
            return
        try:
            from thomas.server.routes.spend import register_spend_routes

            register_spend_routes(app_ref, require_api_access=_require_api_access)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Spend routes unavailable: %s", e)

    _register_spend_routes(app)

    def _register_workspace_routes(app_ref: web.Application, cfg_ref: AppConfig) -> None:
        """Register multi-tenant workspace APIs."""
        if not callable(_require_api_access):
            log.warning("Workspace route registration skipped: missing API access guard")
            return
        try:
            from thomas.server.workspace.router import setup as setup_workspace_router

            setup_workspace_router(
                app_ref,
                cfg_ref,
                require_api_access=_require_api_access,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Workspace routes unavailable: %s", e)

    _register_workspace_routes(app, config)

    def _register_local_project_routes(app_ref: web.Application) -> None:
        """Register local project APIs used by the My Stuff workspace."""
        if not all(callable(dep) for dep in (_require_api_access, _require_loopback, _read_json)):
            log.warning("Local project route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.local_projects_aiohttp import register_local_project_routes

            register_local_project_routes(
                app_ref,
                require_api_access=_require_api_access,
                require_loopback=_require_loopback,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Local project routes unavailable: %s", e)

    _register_local_project_routes(app)

    def _register_marketplace_routes(app_ref: web.Application) -> None:
        """Register marketplace catalog, hosted plugin-store, and Life Manager routes."""
        if not callable(_require_api_access):
            log.warning("Marketplace route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.inkwell_aiohttp import register_inkwell_routes
            from thomas.server.routes.life_manager_aiohttp import register_life_manager_routes
            from thomas.server.routes.marketplace_catalog_aiohttp import register_marketplace_catalog_routes
            from thomas.server.routes.paper_trading_aiohttp import register_paper_trading_routes
            from thomas.server.routes.plugin_hosting import register_plugin_hosting_routes
            from thomas.server.routes.standalone_app_aiohttp import register_standalone_app_routes

            register_marketplace_catalog_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
            register_plugin_hosting_routes(app_ref)
            register_life_manager_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
            register_inkwell_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
            register_standalone_app_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
            register_paper_trading_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Marketplace routes unavailable: %s", e)

    _register_marketplace_routes(app)

    def _register_openai_codex_routes(app_ref: web.Application) -> None:
        """Register native ChatGPT/Codex OAuth APIs used by onboarding and model setup."""
        if not callable(_require_api_access):
            log.warning("Native ChatGPT/Codex route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.openai_codex_aiohttp import register_openai_codex_routes

            register_openai_codex_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Native ChatGPT/Codex routes unavailable: %s", e)

    _register_openai_codex_routes(app)

    def _register_mission_routes(app_ref: web.Application, cfg_ref: AppConfig) -> None:
        """Register Mission Control APIs used by the main Thomas shell."""
        if not callable(_require_api_access):
            log.warning("Mission routes unavailable: missing API access guard")
            return
        try:
            from thomas.server.routes.mission import register_mission_routes

            register_mission_routes(
                app_ref,
                web_dir=web_dir,
                require_api_access=_require_api_access,
                run_store_enabled_key=APP_RUN_STORE_ENABLED,
                run_store_module_key=APP_RUN_STORE_MODULE,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Mission routes unavailable: %s", e)

    def _register_observability_routes(app_ref: web.Application) -> None:
        """Register system monitoring APIs used by the main shell."""
        try:
            from thomas.server.routes.observability import register_observability_routes

            register_observability_routes(app_ref)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Observability routes unavailable: %s", e)

    _register_observability_routes(app)

    def _register_deliverable_routes(app_ref: web.Application) -> None:
        """Serve worker-built deliverables (generated games/apps) for one-click Play."""
        if not callable(_require_api_access):
            log.warning("Deliverable routes unavailable: missing API access guard")
            return
        try:
            from thomas.server.routes.deliverable_aiohttp import register_deliverable_routes

            register_deliverable_routes(app_ref, require_api_access=_require_api_access)
        except (ImportError, ModuleNotFoundError, RuntimeError) as e:
            log.warning("Deliverable routes unavailable: %s", e)

    _register_deliverable_routes(app)

    def _register_chat_v2_routes(app_ref: web.Application, cfg_ref: AppConfig) -> None:
        """Register the unified V2 chat routes when the supporting modules are available."""
        if not callable(_require_api_access):
            log.warning("Chat V2 routes unavailable: missing API access guard")
            return
        try:
            from thomas.server.routes.chat_v2 import register_chat_v2_routes

            register_chat_v2_routes(
                app_ref,
                config=cfg_ref,
                llm=None,
                memory=app_ref.get(APP_MEMORY),
                tools=app_ref.get(APP_TOOLS),
                chat_store_dir=cfg_ref.memory.root_path / ".thomas" / "sessions_v2",
                require_api_access=_require_api_access,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Chat V2 routes unavailable: %s", e)

    def _register_evolve_loop_routes(app_ref: web.Application) -> None:
        """Register the self-recursive evolve loop dashboard API."""
        if not callable(_require_api_access):
            log.warning("Evolve loop routes unavailable: missing API access guard")
            return
        try:
            from thomas.server.routes.evolve_loop_routes import register_evolve_loop_routes

            register_evolve_loop_routes(app_ref, require_api_access=_require_api_access)
            # Directed Evolve agent (Thomas's self-builder: direct engineering
            # session, no dispatcher). Registered alongside the autonomous loop.
            from thomas.server.routes.evolve_agent_routes import register_evolve_agent_routes

            register_evolve_agent_routes(app_ref, require_api_access=_require_api_access)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Evolve loop routes unavailable: %s", e)

    def _register_work_routes(app_ref: web.Application) -> None:
        """Register native Work metadata and delegate every automation to Mission."""

        if not callable(_require_api_access):
            log.warning("Work routes unavailable: missing API access guard")
            return
        try:
            from thomas.autonomy.scheduler import compute_next_run
            from thomas.server.routes.mission import APP_MISSION_REQUIRE_STORE, APP_MISSION_WAKEUP_ENGINE
            from thomas.server.routes.work import register_work_routes

            async def submit_to_mission(payload: dict[str, Any]) -> dict[str, Any]:
                require_store = app_ref.get(APP_MISSION_REQUIRE_STORE)
                if not callable(require_store):
                    raise RuntimeError("Mission store is unavailable")
                store = await require_store(auto_enable=True)
                now = datetime.now(timezone.utc)
                schedule = payload.get("schedule") if isinstance(payload.get("schedule"), dict) else None
                run_at = None
                if payload.get("run_at"):
                    run_at = datetime.fromisoformat(str(payload["run_at"]).replace("Z", "+00:00"))
                    run_at = run_at if run_at.tzinfo else run_at.replace(tzinfo=timezone.utc)
                next_run_at = compute_next_run(schedule, now) if schedule else (run_at or now)
                if next_run_at is None:
                    raise RuntimeError("Mission schedule does not produce a future run")
                job_payload = dict(payload.get("payload") or {})
                for key in ("goal", "prompt", "workflow", "profile", "model_id"):
                    if payload.get(key):
                        job_payload[key] = payload[key]
                delivery_id = str(job_payload.get("work_event_delivery_id") or "").strip()
                mission_job_id = (
                    hashlib.sha256(f"thomas-work:{delivery_id}".encode()).hexdigest()[:32] if delivery_id else ""
                )
                existing_job = None
                if mission_job_id:
                    try:
                        existing_job = store.get_job(mission_job_id)
                    except KeyError:
                        existing_job = None
                    if (
                        existing_job is not None
                        and str(existing_job.payload.get("work_event_delivery_id") or "") != delivery_id
                    ):
                        raise RuntimeError("Mission idempotency identity conflict")
                try:
                    job = existing_job or store.create_job(
                        name=str(payload.get("name") or "Work automation"),
                        kind=str(payload.get("kind") or "workflow_task"),
                        payload=job_payload,
                        schedule=schedule,
                        next_run_at=next_run_at,
                        risk_class=str(payload.get("risk_class") or "low"),
                        requires_approval=bool(payload.get("requires_approval")),
                        parent_id=str(payload.get("parent_id") or "") or None,
                        session_id=str(payload.get("session_id") or "") or None,
                        job_id=mission_job_id or None,
                    )
                except sqlite3.IntegrityError:
                    if not mission_job_id:
                        raise
                    job = store.get_job(mission_job_id)
                    if str(job.payload.get("work_event_delivery_id") or "") != delivery_id:
                        raise RuntimeError("Mission idempotency identity conflict") from None
                wakeup = app_ref.get(APP_MISSION_WAKEUP_ENGINE)
                if callable(wakeup):
                    wakeup()
                return {"job_id": str(getattr(job, "id", "") or "")}

            async def read_mission_status(job_id: str) -> dict[str, Any] | None:
                require_store = app_ref.get(APP_MISSION_REQUIRE_STORE)
                if not callable(require_store):
                    raise RuntimeError("Mission store is unavailable")
                try:
                    store = await require_store(auto_enable=True)
                except web.HTTPNotFound as exc:
                    raise RuntimeError("Mission store is unavailable") from exc
                try:
                    job = store.get_job(job_id)
                except KeyError:
                    return None
                return {
                    "id": str(getattr(job, "id", "") or ""),
                    "status": str(getattr(job, "status", "") or ""),
                    "result": getattr(job, "result", None) or {},
                    "error": getattr(job, "error", None) or {},
                    "updated_at": str(getattr(job, "updated_at", "") or ""),
                }

            async def cancel_mission(job_id: str) -> dict[str, Any]:
                require_store = app_ref.get(APP_MISSION_REQUIRE_STORE)
                if not callable(require_store):
                    raise RuntimeError("Mission store is unavailable")
                store = await require_store(auto_enable=True)
                try:
                    store.get_job(job_id)
                except KeyError as exc:
                    raise RuntimeError("Mission job is unavailable") from exc
                store.cancel_job(job_id, actor="work")
                job = store.get_job(job_id)
                return {
                    "id": str(getattr(job, "id", "") or ""),
                    "status": str(getattr(job, "status", "") or ""),
                    "updated_at": str(getattr(job, "updated_at", "") or ""),
                }

            register_work_routes(
                app_ref,
                require_api_access=_require_api_access,
                mission_submitter=submit_to_mission,
                mission_status_provider=read_mission_status,
                mission_canceller=cancel_mission,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Work routes unavailable: %s", e)

    _register_chat_v2_routes(app, config)
    _register_mission_routes(app, config)
    _register_work_routes(app)
    _register_evolve_loop_routes(app)

    # Server restart endpoint
    async def api_server_restart(request: web.Request) -> web.Response:
        """Request server restart."""
        _require_loopback(request)
        app[APP_RESTART_REQUESTED] = True
        shutdown_event = app.get(APP_SHUTDOWN_EVENT)
        if shutdown_event:
            shutdown_event.set()
        return web.json_response({"restarting": True})

    # Register routes
    app.router.add_post("/api/server/restart", api_server_restart)
    app.router.add_get("/", index)

    async def favicon(_request: web.Request) -> web.Response:
        return web.Response(
            text=(
                "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
                "<rect width='100' height='100' rx='24' fill='#8b8cff'/>"
                "<text x='50' y='72' text-anchor='middle' font-family='sans-serif' "
                "font-size='64' font-weight='700' fill='white'>T</text></svg>"
            ),
            content_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    app.router.add_get("/favicon.ico", favicon)
    if classic is not None:
        app.router.add_get("/classic", classic)
    app.router.add_get("/mission", index)
    app.router.add_get("/settings", settings)
    app.router.add_get("/companion", companion)
    app.router.add_get("/landing", landing)

    async def my_stuff_page(request: web.Request) -> web.StreamResponse:
        _ = request
        my_stuff_html = (web_dir / "static" / "my_stuff.html").resolve()
        static_root = (web_dir / "static").resolve()
        if not my_stuff_html.is_relative_to(static_root) or not my_stuff_html.is_file():
            raise web.HTTPNotFound()
        try:
            html = await asyncio.to_thread(my_stuff_html.read_text, encoding="utf-8", errors="replace")
            web_build = (
                _web_build_fingerprint(
                    "static/my_stuff.html",
                    "static/my_stuff.style01.css",
                    "static/my_stuff.script01.js",
                    "js/workspace_shell.js",
                    "js/ui_edit_layout.js",
                    "js/ui_edit_mode.js",
                    "css/workspace_shell.css",
                    "css/ui_edit_mode.css",
                )
                if callable(_web_build_fingerprint)
                else "dev"
            )
            return web.Response(
                text=html.replace("__THOMAS_WEB_BUILD__", web_build),
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(my_stuff_html)

    app.router.add_get("/my-stuff", my_stuff_page)
    app.router.add_get("/my-stuff/", my_stuff_page)
    app.router.add_get("/my_stuff", my_stuff_page)
    app.router.add_get("/my_stuff/", my_stuff_page)

    app.router.add_get("/api/task_ledger/current", api_task_ledger_current)
    app.router.add_get("/api/task-ledger/current", api_task_ledger_current)
    app.router.add_get("/api/task_ledger/history", api_task_ledger_history)
    app.router.add_get("/api/task-ledger/history", api_task_ledger_history)
    app.router.add_get("/api/security/mutating_routes", api_security_mutating_routes)
    app.router.add_get("/api/security/mutating-routes", api_security_mutating_routes)
    app.router.add_get("/api/engines", api_engines)
    app.router.add_get("/api/tools", api_tools)
    app.router.add_get("/api/chats", api_chats)
    app.router.add_put("/api/chats", api_chat_put)
    app.router.add_put("/api/chats/{chat_id}", api_chat_put)
    app.router.add_delete("/api/chats/{chat_id}", api_chat_delete)

    async def static_compat(request: web.Request) -> web.StreamResponse:
        """Serve both modern shell assets and legacy module files under /static/."""
        raw_path = str(request.match_info.get("path", "") or "").replace("\\", "/").lstrip("/")
        rel_path = Path(raw_path)
        if not raw_path or rel_path.is_absolute() or ".." in rel_path.parts:
            raise web.HTTPNotFound()

        # Confine the resolved target inside one of the intended base directories.
        # Resolving first defends against symlink escapes that the parts() check
        # above cannot catch (py/path-injection).
        base_dirs = (web_dir.resolve(), (web_dir / "static").resolve())
        for base in base_dirs:
            candidate = (base / rel_path).resolve()
            if not candidate.is_relative_to(base):
                continue
            if candidate.is_file():
                response = web.FileResponse(candidate)
                guessed_type, _ = mimetypes.guess_type(str(candidate))
                if guessed_type:
                    response.content_type = guessed_type
                return response
        raise web.HTTPNotFound()

    app.router.add_get("/static/{path:.*}", static_compat, name="static")

    # Build mutating route policy snapshot
    def _build_mutating_route_policy_snapshot() -> dict[str, Any]:
        """Build security policy snapshot for all mutating routes."""
        policies: list[dict[str, Any]] = []
        for resource in app.router.resources():
            for route in resource:
                method = str(route.method or "GET").upper()
                if method not in {"POST", "PUT", "PATCH", "DELETE"}:
                    continue

                raw_path = str(resource.canonical or "")
                sample_path = re.sub(r"\{[^}]+\}", "audit", raw_path)

                if raw_path.startswith("/webhooks/receive/"):
                    policies.append(
                        {
                            "method": method,
                            "path": raw_path,
                            "sample_path": sample_path,
                            "authz": "webhook_provider_signature_or_secret",
                            "csrf": "not_applicable_webhook_receiver",
                            "enforced_by": ["webhook_provider_signature_validation"],
                        }
                    )
                    continue
                if (
                    sample_path.startswith("/api/")
                    or sample_path.startswith("/gateway/")
                    or sample_path.startswith("/openai-compat/")
                    or sample_path.startswith("/v1/")
                    or sample_path == "/probe"
                ):
                    policies.append(
                        {
                            "method": method,
                            "path": raw_path,
                            "sample_path": sample_path,
                            "authz": "require_api_access",
                            "csrf": "same_origin_or_optional_custom_header",
                            "enforced_by": ["authz_guard_mutating_api", "csrf_guard_mutating_api"],
                        }
                    )
                    continue
                policies.append(
                    {
                        "method": method,
                        "path": raw_path,
                        "sample_path": sample_path,
                        "authz": "unknown",
                        "csrf": "unknown",
                        "enforced_by": [],
                    }
                )
        policies.sort(key=lambda row: (str(row.get("method") or ""), str(row.get("sample_path") or "")))
        return {
            "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "defaults": {"authz": "require_api_access", "csrf": "same_origin_or_optional_custom_header"},
            "route_count": len(policies),
            "policies": policies,
        }

    app[APP_MUTATING_ROUTE_POLICY_SNAPSHOT] = _build_mutating_route_policy_snapshot()
