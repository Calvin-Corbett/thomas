"""Route handlers and final app setup for Thomas server."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.core.config import AppConfig
from thomas.server.app_keys import (
    APP_CODEX_BRIDGE,
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
from thomas.tools.registry import ToolRegistry

from .app_runtime_guard import _runtime_guard_loop

if TYPE_CHECKING:
    from aiohttp import web

log = logging.getLogger(__name__)
_RUN_STORE_JANITOR_INTERVAL_SECONDS = 120
_RUN_STORE_STALE_IDLE_SECONDS = 10 * 60


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
    index = locals_dict.get("index")
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
                if inferred_missing:
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
        """List all chats from disk storage."""
        _require_api_access(request)
        chats = await _load_all_chats_from_disk()
        return web.json_response({"chats": chats})

    async def api_chat_put(request: web.Request) -> web.Response:
        """Save or update a chat."""
        _require_api_access(request)
        if not _is_json_content_type(request):
            raise web.HTTPBadRequest(text="Content-Type must be application/json")

        payload = await _read_json(request)
        chat = _sanitize_chat_payload(payload)
        await _save_chat_to_disk(chat)
        return web.json_response(chat, status=201)

    async def api_chat_delete(request: web.Request) -> web.Response:
        """Delete a chat."""
        _require_api_access(request)
        chat_id = request.match_info.get("chat_id", "")
        if not chat_id:
            raise web.HTTPBadRequest(text="missing chat_id")

        deleted = await _delete_chat_from_disk(chat_id)
        if not deleted:
            raise web.HTTPNotFound(text=f"chat {chat_id} not found")
        return web.Response(status=204)

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

    async def on_cleanup(app_ref: web.Application) -> None:
        """App cleanup handler."""
        nonlocal run_store_janitor_task
        guard_task = app_ref.get(APP_RUNTIME_GUARD_TASK)
        if guard_task:
            guard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await guard_task
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

    def _register_chat_and_session_routes(app_ref: web.Application, cfg_ref: AppConfig) -> None:
        """Register the live session/chat route bundles when their deps are available."""
        if not all(
            callable(dep)
            for dep in (
                _require_api_access,
                _read_json,
                _session_lock_for,
                _begin_session_run,
                _end_session_run,
                _task_ledger_update,
                _model_cfg_with_secrets,
                _failover_cfgs_with_secrets,
                _resolve_natural_model_switch_request,
                _chat_file_for,
                _read_chat_from_disk,
                _save_chat_to_disk,
                _build_tools,
            )
        ):
            log.warning("Chat/session route registration skipped: missing runtime dependencies")
            return

        try:
            from thomas.server.routes.chat_aiohttp import ChatRouteDeps, register_chat_routes
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

            def _model_cfg_for_profile(profile: str) -> Any:
                model_cfg = cfg_ref.models.get(profile)
                if model_cfg is None:
                    raise KeyError(profile)
                return _model_cfg_with_secrets(cfg_ref, profile, model_cfg)

            def _failover_cfgs_for_profile(profile: str) -> list[Any]:
                return list(_failover_cfgs_with_secrets(cfg_ref, profile) or [])

            async def _resolve_model_switch(text: str, current_profile: str = "") -> str | None:
                return await _resolve_natural_model_switch_request(
                    text,
                    user_id="default",
                    session_id=current_profile,
                )

            def _build_tools_for_runtime(runtime_cfg: AppConfig) -> Any:
                return _build_tools(runtime_cfg)

            register_sessions_routes(
                app_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
                task_ledger_update=_task_ledger_update_compat,
            )
            register_chat_routes(
                app_ref,
                deps=ChatRouteDeps(
                    require_api_access=_require_api_access,
                    read_json=_read_json,
                    session_lock_for=_session_lock_for,
                    begin_session_run=_begin_session_run,
                    end_session_run=_end_session_run,
                    task_ledger_update=_task_ledger_update_compat,
                    model_cfg_with_secrets=_model_cfg_for_profile,
                    failover_cfgs_with_secrets=_failover_cfgs_for_profile,
                    resolve_natural_model_switch=_resolve_model_switch,
                    chat_file_for=_chat_file_for,
                    read_chat_from_disk=_read_chat_from_disk,
                    save_chat_to_disk=_save_chat_to_disk,
                    build_tools=_build_tools_for_runtime,
                ),
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Chat/session routes unavailable: %s", e)

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
            from thomas.server.routes.life_manager_aiohttp import register_life_manager_routes
            from thomas.server.routes.marketplace_catalog_aiohttp import register_marketplace_catalog_routes
            from thomas.server.routes.plugin_hosting import register_plugin_hosting_routes

            register_marketplace_catalog_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
            register_plugin_hosting_routes(app_ref)
            register_life_manager_routes(
                app_ref,
                require_api_access=_require_api_access,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Marketplace routes unavailable: %s", e)

    _register_marketplace_routes(app)

    def _register_codex_routes(app_ref: web.Application) -> None:
        """Register Codex bridge APIs used by onboarding and identity UI."""
        if not callable(_require_api_access):
            log.warning("Codex route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.codex_aiohttp import register_codex_routes

            register_codex_routes(
                app_ref,
                require_api_access=_require_api_access,
                codex_bridge_key=APP_CODEX_BRIDGE,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Codex routes unavailable: %s", e)

    _register_codex_routes(app)

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

    def _register_chat_v2_routes(app_ref: web.Application, cfg_ref: AppConfig) -> None:
        """Register the unified V2 chat routes when the supporting modules are available."""
        try:
            from thomas.server.routes.chat_v2 import register_chat_v2_routes

            register_chat_v2_routes(
                app_ref,
                config=cfg_ref,
                llm=None,
                memory=app_ref.get(APP_MEMORY),
                tools=app_ref.get(APP_TOOLS),
                chat_store_dir=cfg_ref.memory.root_path / ".thomas" / "sessions_v2",
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Chat V2 routes unavailable: %s", e)

    _register_chat_v2_routes(app, config)
    _register_mission_routes(app, config)

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
    app.router.add_get("/mission", index)
    app.router.add_get("/settings", settings)
    app.router.add_get("/companion", companion)
    app.router.add_get("/landing", landing)

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

        candidates = (
            web_dir / rel_path,
            web_dir / "static" / rel_path,
        )
        for candidate in candidates:
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
                sample_path = raw_path.replace("{", ":").replace("}", "")

                if raw_path.startswith("/webhooks/receive/"):
                    policies.append(
                        {
                            "method": method,
                            "path": raw_path,
                            "sample_path": sample_path,
                            "authz": "optional_signature_or_secret",
                            "csrf": "not_applicable_webhook_receiver",
                            "enforced_by": ["webhook_provider_signature_validation"],
                        }
                    )
                    continue
                if (
                    sample_path.startswith("/api/")
                    or sample_path.startswith("/gateway/")
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
