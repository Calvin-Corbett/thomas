"""Route handlers and final app setup for the Thomas server."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import mimetypes
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.core.config import AppConfig
from thomas.core.event_loop_lag import start_loop_watch
from thomas.core.event_loop_offload import off_loop
from thomas.server.app_keys import (
    APP_CHAT_TURN_HANDLER,
    APP_DIAGNOSTICS,
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
from thomas.server.plugin_startup import dispose_plugin_handles, mount_plugin_handles
from thomas.server.routes.chat_surface_namespace import normalize_workspace_context_id
from thomas.server.routes.evolve_agent_run_state import active_code_runs
from thomas.server.routes.version_aiohttp import register_version_route
from thomas.tools.registry import ToolRegistry

from .app_chat_store import _v2_sessions_as_chats, delete_live_chat
from .app_routes_chat_storage import build_chat_storage_handlers
from .app_routes_families import register_late_route_families, register_optional_route_families
from .app_routes_task_ledger import build_task_ledger_handlers
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
    _model_cfg_with_secrets = locals_dict.get("_model_cfg_with_secrets")
    _failover_cfgs_with_secrets = locals_dict.get("_failover_cfgs_with_secrets")
    _chat_file_for = locals_dict.get("_chat_file_for")
    _read_chat_from_disk = locals_dict.get("_read_chat_from_disk")
    _build_tools = locals_dict.get("_build_tools")
    _web_build_fingerprint = locals_dict.get("_web_build_fingerprint")
    index = locals_dict.get("index")
    classic = locals_dict.get("classic")
    settings = locals_dict.get("settings")
    companion = locals_dict.get("companion")

    # The task-ledger and diagnostics handlers are built in app_routes_task_ledger.py;
    # the security snapshot is still registered below, by name.

    _ledger_handlers = build_task_ledger_handlers(app, require_api_access=_require_api_access)
    api_security_mutating_routes = _ledger_handlers["api_security_mutating_routes"]

    # Chat storage routes
    # The chat storage handlers are built in app_routes_chat_storage.py; the
    # registration below and the run-store janitor keep using their names.

    _chat_handlers = build_chat_storage_handlers(
        config,
        require_api_access=_require_api_access,
        read_json=_read_json,
        is_json_content_type=_is_json_content_type,
        load_all_chats_from_disk=_load_all_chats_from_disk,
        save_chat_to_disk=_save_chat_to_disk,
        delete_chat_from_disk=_delete_chat_from_disk,
        sanitize_chat_payload=_sanitize_chat_payload,
    )
    api_chats = _chat_handlers["api_chats"]
    api_chat_put = _chat_handlers["api_chat_put"]
    api_chat_delete = _chat_handlers["api_chat_delete"]

    run_store_janitor_task: asyncio.Task | None = None

    async def _run_store_janitor(app_ref: web.Application) -> None:
        while True:
            await asyncio.sleep(_RUN_STORE_JANITOR_INTERVAL_SECONDS)
            if not bool(app_ref.get(APP_RUN_STORE_ENABLED)):
                continue
            run_store_mod = app_ref.get(APP_RUN_STORE_MODULE)
            if run_store_mod is None:
                continue
            active = frozenset(active_code_runs(app_ref).values())
            try:
                # The run store's files on another thread: on the event loop this sweep stalled every request while
                # the disk was busy (freeze dumps, 2026-10-27).
                reconciled = int(
                    await off_loop(
                        "run_store.janitor",
                        run_store_mod.reconcile_stale_runs,
                        idle_seconds=_RUN_STORE_STALE_IDLE_SECONDS,
                        reason="stale run janitor reconciliation",
                        active_run_ids=active,
                    )
                    or 0
                )
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as janitor_exc:
                # Named, not broad: a storage hiccup skips one sweep; a bug in
                # the janitor itself still surfaces.
                log.debug("Run store janitor skipped: %s", janitor_exc)
                continue
            if reconciled:
                log.warning("Run store janitor reconciled %d stale runs", reconciled)

    # Startup and cleanup
    async def on_startup(app_ref: web.Application) -> None:
        """App startup handler."""
        nonlocal run_store_janitor_task
        from thomas.server import server_lifetime

        server_lifetime.started()  # and whether the server before this one died with its runs going
        guard_task = asyncio.create_task(_runtime_guard_loop(app_ref))
        app_ref[APP_RUNTIME_GUARD_TASK] = guard_task
        # Measures what "the server stopped answering" actually is: how late the
        # loop woke a coroutine that asked for a quarter second. Read back through
        # /api/landing-health, and logged at warning past its budget.
        start_loop_watch(app_ref)
        # A row's own startup hooks begin here, and this start does not wait for them.
        runtime.mark_ready()

        # Phase 3.5: the installed plugins mount under a supervisor that can
        # unplug, replug and reload them while Thomas runs, and the other three
        # plugin systems mount as kernel services. Both mounts, and the reason
        # each gets its own try, live in plugin_startup.
        mount_plugin_handles(app_ref)

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
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as startup_exc:
                # Named, not broad -- same contract as the janitor above.
                log.debug("Run store startup reconciliation skipped: %s", startup_exc)
            else:
                if reconciled:
                    log.warning("Run store reconciled %d orphaned runs on startup", reconciled)
            run_store_janitor_task = asyncio.create_task(_run_store_janitor(app_ref))

        # A build paused on your model provider's usage limit carries on by itself once it resets (off in tests),
        # and so does a run on Autopilot that the last restart stopped.
        from thomas.server.autopilot_park import start_park_loop
        from thomas.server.autopilot_restart import start_restart_pass

        start_park_loop(app_ref)
        start_restart_pass(app_ref)

        # Windows Search leaves the folders Thomas keeps rewriting alone (thomas/core/unindexed.py); off in tests,
        # which must never mark your real checkout.
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            from thomas.core import unindexed

            app_ref["unindexed_task"] = asyncio.create_task(
                asyncio.to_thread(unindexed.mark_folders, unindexed.thomas_folders())
            )

    async def on_cleanup(app_ref: web.Application) -> None:
        """App cleanup handler."""
        nonlocal run_store_janitor_task
        from thomas.server import server_lifetime

        server_lifetime.exited()
        if not os.environ.get("PYTEST_CURRENT_TEST"):  # a test's server must not leave a thread behind it
            from thomas.core.event_loop_lag import watch_shutdown

            watch_shutdown()  # a shutdown still going after 20 s writes where every thread is (2026-11-09)
        await runtime.stop_all()
        for key in (APP_RUNTIME_GUARD_TASK, "event_loop_lag_task"):
            task = app_ref.get(key)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    # Broad catch: a dead background task must not skip the rest of shutdown.
                    log.exception("Background task %s failed during cleanup", key)
        from thomas.server.autopilot_park import stop_park_loop
        from thomas.server.autopilot_restart import stop_restart_pass

        await stop_park_loop(app_ref)
        await stop_restart_pass(app_ref)
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

        # Unmount the plugins, which unwinds every hook subscription they made.
        # This is the property the kernel exists for: teardown is not a second
        # implementation that has to be kept in step with setup.
        dispose_plugin_handles(app_ref)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    # Gateway routing
    # The optional route families live in app_routes_families.py: this body sits
    # under the hard ceiling test_file_sizes enforces on push.

    register_optional_route_families(
        app,
        config,
        require_api_access=_require_api_access,
        read_json=_read_json,
        require_loopback=_require_loopback,
        model_cfg_with_secrets=_model_cfg_with_secrets,
        log=log,
    )

    # Rows load here: the config turns each on or off, except a required row, which always loads. Companion was the
    # first family to move.
    from thomas.server.runtime_plugins import load_runtime_plugins

    runtime = load_runtime_plugins(
        app,
        config,
        require_api_access=_require_api_access,
        read_json=_read_json,
        require_loopback=_require_loopback,
        web_dir=web_dir,
    )

    # Nine more optional route families live in app_routes_families.py (second cut).
    register_late_route_families(
        app,
        config,
        web_dir=web_dir,
        require_api_access=_require_api_access,
        read_json=_read_json,
        require_loopback=_require_loopback,
        log=log,
    )

    def _register_chat_unavailable_sentinel(app_ref: web.Application, detail: str) -> None:
        """Answer the chat endpoints with a deterministic 503 instead of nothing.

        Chat V2 is the ONLY registrar of POST /api/chat, so a registration
        failure used to leave the route unclaimed: the browser got a bare 404
        that reads like a client bug, and the sole trace was one log line in a
        console nobody had open. The sentinel makes the failure self-reporting
        at the exact place the caller notices it.
        """

        async def api_chat_unavailable(request: web.Request) -> web.Response:
            # After Try again the chat row cannot claim these two paths, so it hands the turn handler to this answer.
            forward = app_ref.get(APP_CHAT_TURN_HANDLER)
            if forward is not None:
                return await forward(request)
            if callable(_require_api_access):
                _require_api_access(request)
            log.error("POST %s rejected: Chat V2 never registered (%s)", request.path, detail)
            return web.json_response(
                {
                    "error": (
                        "Chat is unavailable: the Chat V2 route bundle failed to register at "
                        "startup, and no other module serves /api/chat."
                    ),
                    "code": "chat_v2_registration_failed",
                    "detail": detail,
                },
                status=503,
            )

        app_ref.router.add_post("/api/chat", api_chat_unavailable)
        app_ref.router.add_post("/api/v2/chat", api_chat_unavailable)

    def _chat_registration_failed(app_ref: web.Application, detail: str) -> None:
        """Make a missing chat endpoint loud on every surface that reports health."""
        log.error(
            "Chat V2 route registration FAILED (%s). POST /api/chat and /api/v2/chat now answer "
            "503 chat_v2_registration_failed, and /api/health reports chat as degraded.",
            detail,
        )
        diagnostics = app_ref.get(APP_DIAGNOSTICS)
        if isinstance(diagnostics, dict):
            diagnostics["chat"] = False
        _register_chat_unavailable_sentinel(app_ref, detail)
        try:
            from thomas.server.issue_ledger import record_issue

            record_issue(
                surface="server",
                kind="chat_endpoint_missing",
                message="Chat V2 routes failed to register; POST /api/chat answers 503",
                context={"detail": detail},
            )
        except (ImportError, ModuleNotFoundError, OSError, TypeError, ValueError) as ledger_exc:
            log.debug("Issue ledger unavailable for the chat registration failure: %s", ledger_exc)

    # Chat is a required row. Its failing to start leaves POST /api/chat answering 503 and health degraded.
    chat_row = next((row for row in runtime.report()["rows"] if row["id"] == "chat"), None)
    if chat_row is not None and chat_row["state"] == "failed":
        _chat_registration_failed(app, chat_row["error"])

    # Server restart endpoint
    async def api_server_restart(request: web.Request) -> web.Response:
        """Restart once running checks and yielded Build work have drained (owner_restart); never refused for them."""
        from thomas.server.owner_restart import request_restart

        _require_loopback(request)
        return web.json_response({"ok": True, **request_restart(app)}, status=202)

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

    async def to_agents_page(request: web.Request) -> web.StreamResponse:
        """The old Mission Control and Agent Ops addresses lead to the Agents workspace, so saved links keep working."""
        raise web.HTTPFound("/agents?embed=1" if request.query.get("embed") == "1" else "/agents")

    app.router.add_get("/mission", to_agents_page)
    app.router.add_get("/settings", settings)
    app.router.add_get("/companion", companion)

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

    app.router.add_get("/agent-ops", to_agents_page)
    app.router.add_get("/agent-ops/", to_agents_page)
    app.router.add_get("/my_stuff", my_stuff_page)
    app.router.add_get("/my_stuff/", my_stuff_page)

    app.router.add_get("/api/security/mutating_routes", api_security_mutating_routes)
    app.router.add_get("/api/security/mutating-routes", api_security_mutating_routes)
    register_version_route(app, require_api_access=_require_api_access)
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

    def _refresh_mutating_route_policy_snapshot() -> None:
        # Through _state, as at APP_RESTART_REQUESTED above: a plugin can turn off or on after the app has frozen.
        app._state[APP_MUTATING_ROUTE_POLICY_SNAPSHOT] = _build_mutating_route_policy_snapshot()

    _refresh_mutating_route_policy_snapshot()
    runtime.web.after_publish(_refresh_mutating_route_policy_snapshot)
