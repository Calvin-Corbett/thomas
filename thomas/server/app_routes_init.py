"""Route handlers and final app setup for Thomas server."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import mimetypes
import time
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
    APP_SHUTDOWN_EVENT,
    APP_TASK_LEDGER,
    APP_TOOLS,
)
from thomas.tools.registry import ToolRegistry

from .app_runtime_guard import _runtime_guard_loop

if TYPE_CHECKING:
    from aiohttp import web

log = logging.getLogger(__name__)


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

        session_id = str(request.query.get("session_id", "")).strip() or None
        snapshot = ledger.snapshot(session_id)
        return web.json_response({"snapshot": snapshot})

    async def api_task_ledger_history(request: web.Request) -> web.Response:
        """Return task ledger history for a session (or latest session)."""
        _require_api_access(request)
        ledger = app.get(APP_TASK_LEDGER)
        if not ledger:
            raise web.HTTPNotFound(text="task ledger unavailable")

        session_id = str(request.query.get("session_id", "")).strip() or None
        history = ledger.history(session_id)
        return web.json_response({"history": history})

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
            return web.json_response({"tools": []})

        tools_list = []
        for tool in registry.tools():
            tool_dict = {
                "name": getattr(tool, "name", ""),
                "description": getattr(tool, "description", ""),
                "category": getattr(tool, "category", ""),
            }
            tools_list.append(tool_dict)
        return web.json_response({"tools": tools_list})

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

    # Startup and cleanup
    async def on_startup(app_ref: web.Application) -> None:
        """App startup handler."""
        guard_task = asyncio.create_task(_runtime_guard_loop(app_ref))
        app_ref[APP_RUNTIME_GUARD_TASK] = guard_task

    async def on_cleanup(app_ref: web.Application) -> None:
        """App cleanup handler."""
        guard_task = app_ref.get(APP_RUNTIME_GUARD_TASK)
        if guard_task:
            guard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await guard_task

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

    def _register_preferences_and_onboarding_routes(app_ref: web.Application) -> None:
        """Register preferences and onboarding APIs once runtime guards exist."""
        if not callable(_require_api_access):
            log.warning("Preferences/onboarding route registration skipped: missing runtime dependencies")
            return
        try:
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
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Preferences/onboarding routes unavailable: %s", e)

    _register_preferences_and_onboarding_routes(app)

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
    app.router.add_get("/api/task_ledger/history", api_task_ledger_history)
    app.router.add_get("/api/security/mutating_routes", api_security_mutating_routes)
    app.router.add_get("/api/engines", api_engines)
    app.router.add_get("/api/tools", api_tools)
    app.router.add_get("/api/chats", api_chats)
    app.router.add_put("/api/chats", api_chat_put)
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
