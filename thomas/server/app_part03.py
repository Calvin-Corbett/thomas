        except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            log.debug("Skipping unreadable chat file %s: %s", path, e)
            return None

    async def _save_chat_to_disk(chat: dict[str, Any]) -> None:
        payload = json.dumps(chat, ensure_ascii=False, separators=(",", ":"))
        path = _chat_file_for(str(chat.get("id") or ""))
        tmp_path = Path(str(path) + ".tmp")
        async with chat_store_lock:
            try:
                await asyncio.to_thread(chat_store_dir.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(tmp_path.write_text, payload, encoding="utf-8")
                await asyncio.to_thread(tmp_path.replace, path)
            except Exception as e:
                log.error("Failed to save chat to disk: %s", e)
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
                raise

    async def _delete_chat_from_disk(chat_id: str) -> bool:
        path = _chat_file_for(chat_id)
        async with chat_store_lock:
            exists = await asyncio.to_thread(path.exists)
            if not exists:
                return False
            await asyncio.to_thread(path.unlink, missing_ok=True)
        return True

    async def _load_all_chats_from_disk() -> list[dict[str, Any]]:
        chats: list[dict[str, Any]] = []
        async with chat_store_lock:
            paths = await asyncio.to_thread(lambda: list(chat_store_dir.glob("*.json")))
        for path in paths:
            chat = await asyncio.to_thread(_read_chat_from_disk, path)
            if chat is not None:
                chats.append(chat)
        chats.sort(key=lambda c: _safe_int(c.get("updatedAt"), 0), reverse=True)
        return chats

    def _web_build_fingerprint(*relative_paths: str) -> str:
        digest = hashlib.sha1()
        for relative in relative_paths:
            try:
                path = web_dir / relative
                stat = path.stat()
                digest.update(relative.encode("utf-8", errors="ignore"))
                digest.update(str(int(stat.st_mtime_ns)).encode("ascii", errors="ignore"))
                digest.update(str(int(stat.st_size)).encode("ascii", errors="ignore"))
            except OSError:
                digest.update(relative.encode("utf-8", errors="ignore"))
                digest.update(b"missing")
        return digest.hexdigest()[:12]

    async def index(request: web.Request) -> web.StreamResponse:
        try:
            html = await asyncio.to_thread(
                lambda: (web_dir / "index.html").read_text(encoding="utf-8", errors="replace")
            )
            web_build = _web_build_fingerprint(
                "js/app.js",
                "js/app_runtime_primary.mjs",
                "js/ui_editor_rescue.js",
                "index.html",
            )
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            html = html.replace("__THOMAS_WEB_BUILD__", web_build)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(web_dir / "index.html")

    async def settings(request: web.Request) -> web.StreamResponse:
        try:
            html = (web_dir / "settings.html").read_text(encoding="utf-8", errors="replace")
            web_build = _web_build_fingerprint(
                "js/app.js",
                "js/app_runtime_primary.mjs",
                "js/ui_editor_rescue.js",
                "index.html",
            )
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            html = html.replace("__THOMAS_WEB_BUILD__", web_build)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(web_dir / "settings.html")

    async def companion(request: web.Request) -> web.StreamResponse:
        try:
            html = (web_dir / "companion.html").read_text(encoding="utf-8", errors="replace")
            web_build = _web_build_fingerprint(
                "js/app.js",
                "js/app_runtime_primary.mjs",
                "js/ui_editor_rescue.js",
                "index.html",
            )
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            html = html.replace("__THOMAS_WEB_BUILD__", web_build)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(web_dir / "companion.html")

    async def landing(request: web.Request) -> web.StreamResponse:
        landing_path = web_dir / "landing.html"
        if not landing_path.exists():
            raise web.HTTPNotFound(text="Landing page not found")
        try:
            html = landing_path.read_text(encoding="utf-8", errors="replace")
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(landing_path)

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ models/profiles/version routes extracted ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ routes/models_aiohttp.py ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ setup/diagnostics/local-pull routes extracted ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ routes/setup_aiohttp.py ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ onboarding routes extracted ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ routes/onboarding_aiohttp.py ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    async def api_task_ledger_current(request: web.Request) -> web.Response:
        """Return current task ledger snapshot for a session (or latest session)."""
        _require_api_access(request)
        ledger = app.get(APP_TASK_LEDGER)
        if ledger is None:
            return web.json_response({"ok": False, "error": "task_ledger_unavailable"}, status=503)

        session_id = str(request.query.get("session_id") or "").strip()
        snapshot = ledger.get_current(session_id) if session_id else ledger.get_latest()
        resolved_sid = session_id or (snapshot.session_id if snapshot is not None else "")
        return web.json_response(
            {
                "ok": True,
                "session_id": resolved_sid or None,
                "state": snapshot.to_dict() if snapshot is not None else None,
            }
        )

    async def api_task_ledger_history(request: web.Request) -> web.Response:
        """Return task ledger history events for a session."""
        _require_api_access(request)
        ledger = app.get(APP_TASK_LEDGER)
        if ledger is None:
            return web.json_response({"ok": False, "error": "task_ledger_unavailable"}, status=503)

        session_id = str(request.query.get("session_id") or "").strip()
        if not session_id:
            latest = ledger.get_latest()
            if latest is None:
                return web.json_response({"ok": True, "session_id": None, "events": [], "limit": 0})
            session_id = str(latest.session_id)

        try:
            limit = int(request.query.get("limit", "50") or 50)
        except (ValueError, TypeError):
            limit = 50
        limit = max(1, min(limit, 200))
        events = ledger.get_history(session_id, limit=limit)
        return web.json_response(
            {
                "ok": True,
                "session_id": session_id,
                "events": events,
                "limit": limit,
            }
        )

    async def api_security_mutating_routes(request: web.Request) -> web.Response:
        """Return the mutating routes policy snapshot."""
        _require_api_access(request)
        try:
            snapshot = dict(app.get(APP_MUTATING_ROUTE_POLICY_SNAPSHOT) or {})
        except (TypeError, ValueError) as exc:
            snapshot = {"ok": False, "error": str(exc)}
        return web.json_response(snapshot)

    async def api_engines(request: web.Request) -> web.Response:
        """Return status of all background engines."""
        _require_api_access(request)
        manager = app.get(APP_ENGINE_MANAGER)
        if manager is None:
            return web.json_response({"error": "engine manager not available"}, status=503)
        return web.json_response(manager.status())

    async def api_tools(request: web.Request) -> web.Response:
        _require_api_access(request)
        registry: ToolRegistry = app[APP_TOOLS]
        tools = [{"name": t.name, "category": t.category, "description": t.description} for t in registry.list_tools()]
        return web.json_response({"tools": tools})

    async def api_chats(request: web.Request) -> web.Response:
        _require_api_access(request)
        chats = await _load_all_chats_from_disk()
        return web.json_response({"chats": chats}, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_chat_put(request: web.Request) -> web.Response:
        _require_api_access(request)
        chat_id = str(request.match_info.get("chat_id") or "").strip()
        if not chat_id:
            raise web.HTTPBadRequest(text="missing chat id")
        payload = await _read_json(request)
        chat = _sanitize_chat_payload(payload, chat_id=chat_id)
        await _save_chat_to_disk(chat)
        return web.json_response(
            {"ok": True, "chat": chat},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_chat_delete(request: web.Request) -> web.Response:
        _require_api_access(request)
        chat_id = str(request.match_info.get("chat_id") or "").strip()
        if not chat_id:
            raise web.HTTPBadRequest(text="missing chat id")
        deleted = await _delete_chat_from_disk(chat_id)
        return web.json_response({"ok": True, "id": chat_id, "deleted": bool(deleted)})

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ secrets routes extracted ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ routes/secrets_aiohttp.py ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ api_local_pull extracted ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ routes/setup_aiohttp.py ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ session lifecycle routes extracted ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ routes/sessions_aiohttp.py ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ chat execution extracted ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ routes/chat_aiohttp.py ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    async def on_startup(app_: web.Application) -> None:
        task = app_.get(APP_RUNTIME_GUARD_TASK)
        if task is None or task.done():
            app_[APP_RUNTIME_GUARD_TASK] = asyncio.create_task(_runtime_guard_loop(app_))

    async def on_cleanup(app_: web.Application) -> None:
        mem = app_.get(APP_MEMORY)
        if mem is not None:
            try:
                mem.close()
            except (OSError, RuntimeError) as e:
                log.debug("Failed to close memory engine during cleanup: %s", e)
        task = app_.get(APP_RUNTIME_GUARD_TASK)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # Codex (ChatGPT OAuth) endpoints

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    from thomas.server.routes.asset_studio_aiohttp import register_asset_studio_routes
    from thomas.server.routes.codex_aiohttp import register_codex_routes
    from thomas.server.routes.companion_aiohttp import register_companion_routes
    from thomas.server.routes.core_aiohttp import register_core_routes
    from thomas.server.routes.engine_actions_aiohttp import register_engine_actions_routes
    from thomas.server.routes.gateway import p126_gateway_start_command as gateway_start_routes
    from thomas.server.routes.gateway import p127_gateway_restart_command as gateway_restart_routes
    from thomas.server.routes.gateway import p128_gateway_install_command as gateway_install_routes
    from thomas.server.routes.gateway import p129_gateway_uninstall_command as gateway_uninstall_routes
    from thomas.server.routes.gateway import p130_gateway_probe_command as gateway_probe_routes
    from thomas.server.routes.gateway import p131_gateway_discover_command as gateway_discover_routes
    from thomas.server.routes.gateway import p132_gateway_configured_command as gateway_configured_routes
    from thomas.server.routes.gateway import p133_gateway_health_detailed_payload as gateway_health_routes
    from thomas.server.routes.gateway import p134_gateway_usage_cost_command as gateway_usage_cost_routes
    from thomas.server.routes.gateway import p135_gateway_state_persistence_model as gateway_state_persistence_routes
    from thomas.server.routes.gateway import p136_gateway_auth_policy_enforcement as gateway_auth_policy_routes
    from thomas.server.routes.gateway import p137_gateway_logs_filter_command as gateway_logs_filter_routes
    from thomas.server.routes.gateway import p138_gateway_metrics_snapshot_command as gateway_metrics_snapshot_routes
    from thomas.server.routes.gateway import p139_openai_compat_route_scaffold as gateway_openai_compat_routes
    from thomas.server.routes.gateway import p140_openai_chat_completions_non_stream as gateway_openai_non_stream_routes
    from thomas.server.routes.gateway import p141_openai_chat_completions_stream as gateway_openai_stream_routes
    from thomas.server.routes.gateway import p142_openai_tool_call_passthrough_mapping as gateway_tool_call_routes
    from thomas.server.routes.gateway import p144_responses_compat_route_scaffold as gateway_responses_compat_routes
    from thomas.server.routes.gateway import p145_responses_create_non_stream as gateway_responses_create_routes
    from thomas.server.routes.gateway import p146_responses_create_stream_events as gateway_responses_stream_routes
    from thomas.server.routes.gateway import p147_responses_tool_result_mapping as gateway_tool_result_map_routes
    from thomas.server.routes.gateway import p148_compat_model_capability_resolver as gateway_compat_model_routes
    from thomas.server.routes.gateway import p149_compat_request_validation_layer as gateway_compat_validation_routes
    from thomas.server.routes.memory_aiohttp import register_memory_routes
    from thomas.server.routes.life_manager_aiohttp import register_life_manager_routes
    from thomas.server.routes.plugin_hosting import register_plugin_hosting_routes
    from thomas.server.routes.marketplace_catalog_aiohttp import register_marketplace_catalog_routes
    from thomas.server.routes.local_projects_aiohttp import register_local_project_routes
    from thomas.server.routes.mission import register_mission_routes
    from thomas.server.routes.preferences_aiohttp import register_preferences_routes
    from thomas.server.routes.ui_engine_aiohttp import register_ui_engine_routes

    register_codex_routes(
        app,
        require_api_access=_require_api_access,
        codex_bridge_key=APP_CODEX_BRIDGE,
    )
    from thomas.server.routes.chat_aiohttp import ChatRouteDeps, register_chat_routes
    from thomas.server.routes.models_aiohttp import register_models_routes
    from thomas.server.routes.onboarding_aiohttp import register_onboarding_routes
    from thomas.server.routes.secrets_aiohttp import register_secrets_routes
    from thomas.server.routes.sessions_aiohttp import register_sessions_routes
    from thomas.server.routes.setup_aiohttp import register_setup_routes

    register_secrets_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    register_setup_routes(
        app,
        require_api_access=_require_api_access,
        require_loopback=_require_loopback,
        read_json=_read_json,
    )
    register_models_routes(
        app,
        require_api_access=_require_api_access,
        model_cfg_with_secrets=_model_cfg_with_secrets,
    )
    register_onboarding_routes(app, require_api_access=_require_api_access)
    register_sessions_routes(
        app,
        require_api_access=_require_api_access,
        read_json=_read_json,
        task_ledger_update=_task_ledger_update,
    )
    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Chat V1 remains the active /api/chat handler for stable behavior.
    register_chat_routes(
        app,
        deps=ChatRouteDeps(
            require_api_access=_require_api_access,
            read_json=_read_json,
            session_lock_for=_session_lock_for,
            begin_session_run=_begin_session_run,
            end_session_run=_end_session_run,
            task_ledger_update=_task_ledger_update,
            model_cfg_with_secrets=_model_cfg_with_secrets,
            failover_cfgs_with_secrets=_failover_cfgs_with_secrets,
            resolve_natural_model_switch=_resolve_natural_model_switch_request,
            chat_file_for=_chat_file_for,
            read_chat_from_disk=_read_chat_from_disk,
            save_chat_to_disk=_save_chat_to_disk,
            build_tools=_build_tools,
        ),
    )
    try:
        from thomas.server.routes.chat_v2 import register_chat_v2_routes

        register_chat_v2_routes(
            app,
            config=app.get(APP_CONFIG),
            llm=None,  # Specialists manage their own LLM calls
            memory=app.get(APP_MEMORY),
            tools=app.get(APP_TOOLS),
            chat_store_dir=None,  # Uses default .thomas/sessions_v2
        )
    except Exception as exc:
        log.debug("Chat V2 session routes unavailable; V1 chat handler remains active: %s", exc)

    # V3 brain is active via chat_v2.py import swap — no separate routes needed.

    register_preferences_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    from thomas.server.routes.spend import register_spend_routes

    register_spend_routes(app, require_api_access=_require_api_access)
    from thomas.server.routes.goals import register_goals_routes

    register_goals_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    from thomas.server.routes.search import register_search_routes

    register_search_routes(app, require_api_access=_require_api_access)
    try:
        register_asset_studio_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    except Exception as _asset_exc:
        log.warning("Asset studio routes unavailable: %s", _asset_exc)
        _diagnostics["asset_studio"] = False
    register_ui_engine_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    register_engine_actions_routes(
        app,
        require_api_access=_require_api_access,
        read_json=_read_json,
    )
    register_memory_routes(
        app,
        require_api_access=_require_api_access,
        read_json=_read_json,
    )
    register_companion_routes(
        app,
        require_api_access=_require_api_access,
        read_json=_read_json,
        config=config,
    )
    register_mission_routes(
        app,
        web_dir=web_dir,
        require_api_access=_require_api_access,
        run_store_enabled_key=APP_RUN_STORE_ENABLED,
        run_store_module_key=APP_RUN_STORE_MODULE,
    )
    try:
        from thomas.server.workspace.router import setup as setup_workspace_routes

        setup_workspace_routes(app, config, require_api_access=_require_api_access)
    except (ImportError, ModuleNotFoundError, RuntimeError, AttributeError) as e:
        log.warning("Workspace routes unavailable: %s", e)

    def _normalize_gateway_mutating_path(path: str) -> str:
        raw = (path or "").strip()
        if not raw:
            return ""
        if not raw.startswith("/"):
            raw = "/" + raw

        if raw == "/gateway" or raw.startswith("/gateway/"):
            return raw
        if raw == "/v1":
            return "/gateway/v1"
        if raw == "/v1/gateway" or raw.startswith("/v1/gateway/"):
            return raw[len("/v1") :]
        if raw.startswith("/v1/"):
            return "/gateway" + raw
        return "/gateway" + raw

    def _register_gateway_routes(
        module: Any,
        module_name: str,
        *,
        path_transform: Any = None,
    ) -> None:
        source_app = web.Application()
        target_transform = _normalize_gateway_mutating_path if path_transform is None else path_transform

        def _is_duplicate_route_error(exc: RuntimeError) -> bool:
            msg = str(exc).lower()
            return "already registered" in msg or "already exists" in msg or "conflict" in msg or "exists" in msg

        def _register_route_table(target: web.Application, routes_like: Any) -> None:
            if not routes_like:
                return
            try:
                target.router.add_routes(routes_like)
                return
            except RuntimeError as exc:
                if _is_duplicate_route_error(exc):
                    log.debug("%s: duplicate route table entries ignored", module_name)
                    return
                raise
            except TypeError:
                for route_item in routes_like:
                    if route_item is None:
                        continue
                    try:
                        if isinstance(route_item, tuple) and len(route_item) >= 3:
                            target.router.add_route(route_item[0], route_item[1], route_item[2])
                        else:
                            target.router.add_route(route_item.method, route_item.path, route_item.handler)
                    except RuntimeError as exc:
                        if not _is_duplicate_route_error(exc):
                            raise
                        log.debug("%s: duplicate route entry ignored", module_name)

        def _call_hook(hook: Any, hook_name: str) -> bool:
            try:
                signature = inspect.signature(hook)
                params = list(signature.parameters.values())
                if not params:
                    return False

                if params[0].name == "router":
                    hook(source_app.router)
                else:
                    hook(source_app)
                return True
            except TypeError as exc:
                # Mismatched target (typically app/router mix-up) -> ignore after warning.
                log.debug(
                    "Gateway module %s hook %s signature rejected: %s",
                    module_name,
                    hook_name,
                    exc,
                )
                return False
            except RuntimeError as exc:
                if _is_duplicate_route_error(exc):
                    log.debug(
                        "Gateway module %s hook %s produced duplicate routes; ignored",
                        module_name,
                        hook_name,
                    )
                    return True
                raise

        registered = False
        for hook_name in (
            "register",
            "setup_routes",
            "setup",
            "add_routes",
            "bind_routes",
            "register_routes",
        ):
            hook = getattr(module, hook_name, None)
            if not callable(hook):
                continue
            if _call_hook(hook, hook_name):
                registered = True
                break

        if not registered:
            routes_getter = getattr(module, "get_routes", None)
            if callable(routes_getter):
                try:
                    _register_route_table(source_app, routes_getter())
                    registered = True
                except (TypeError, RuntimeError, AttributeError):
                    log.debug("Gateway module %s get_routes registration failed", module_name, exc_info=True)
            if not registered:
                aiohttp_routes_getter = getattr(module, "get_aiohttp_routes", None)
                if callable(aiohttp_routes_getter):
                    try:
                        _register_route_table(source_app, aiohttp_routes_getter())
                        registered = True
                    except (TypeError, RuntimeError, AttributeError):
                        log.debug(
                            "Gateway module %s get_aiohttp_routes registration failed",
                            module_name,
                            exc_info=True,
                        )

        if not registered:
            return

        for route in source_app.router.routes():
            resource = getattr(route, "resource", None)
            if resource is None or not hasattr(resource, "get_info"):
                continue
            method = str(route.method or "").upper()
            if not method:
                continue
            info = resource.get_info()
            raw_path = info.get("path") or info.get("formatter") or info.get("prefix")
            if not isinstance(raw_path, str) or not raw_path.startswith("/"):
                continue
            mapped_path = target_transform(raw_path)
            if not isinstance(mapped_path, str) or not mapped_path.startswith("/"):
                continue
            try:
                app.router.add_route(method, mapped_path, route.handler, name=getattr(route, "name", None))
            except RuntimeError as exc:
                if not _is_duplicate_route_error(exc):
                    raise
                log.debug("%s: duplicate transformed route entry ignored", module_name)

        for key, value in source_app.items():
            if key not in app:
                app[key] = value
        for cleanup_ctx in source_app.cleanup_ctx:
            app.cleanup_ctx.append(cleanup_ctx)

    try:
        _register_gateway_routes(gateway_start_routes, "p126_gateway_start_command")
        _register_gateway_routes(gateway_restart_routes, "p127_gateway_restart_command")
        _register_gateway_routes(gateway_uninstall_routes, "p129_gateway_uninstall_command")
        _register_gateway_routes(gateway_install_routes, "p128_gateway_install_command")
        _register_gateway_routes(gateway_discover_routes, "p131_gateway_discover_command")
        _register_gateway_routes(gateway_configured_routes, "p132_gateway_configured_command")
        _register_gateway_routes(gateway_health_routes, "p133_gateway_health_detailed_payload")
        _register_gateway_routes(gateway_usage_cost_routes, "p134_gateway_usage_cost_command")
        _register_gateway_routes(gateway_state_persistence_routes, "p135_gateway_state_persistence_model")
        _register_gateway_routes(gateway_auth_policy_routes, "p136_gateway_auth_policy_enforcement")
        _register_gateway_routes(gateway_logs_filter_routes, "p137_gateway_logs_filter_command")
        _register_gateway_routes(gateway_metrics_snapshot_routes, "p138_gateway_metrics_snapshot_command")
        _register_gateway_routes(gateway_openai_non_stream_routes, "p140_openai_chat_completions_non_stream")
        _register_gateway_routes(gateway_openai_stream_routes, "p141_openai_chat_completions_stream")
        _register_gateway_routes(gateway_tool_call_routes, "p142_openai_tool_call_passthrough_mapping")
        _register_gateway_routes(gateway_responses_compat_routes, "p144_responses_compat_route_scaffold")
        _register_gateway_routes(gateway_responses_create_routes, "p145_responses_create_non_stream")
        _register_gateway_routes(gateway_responses_stream_routes, "p146_responses_create_stream_events")
        _register_gateway_routes(gateway_tool_result_map_routes, "p147_responses_tool_result_mapping")
        _register_gateway_routes(gateway_compat_model_routes, "p148_compat_model_capability_resolver")
        _register_gateway_routes(gateway_compat_validation_routes, "p149_compat_request_validation_layer")
        _register_gateway_routes(gateway_openai_compat_routes, "p139_openai_compat_route_scaffold")
        _register_gateway_routes(gateway_probe_routes, "p130_gateway_probe_command")
    except (ImportError, ModuleNotFoundError, RuntimeError, AttributeError) as e:
        log.warning("Gateway control routes unavailable: %s", e)

    # Server restart endpoint -- sets shutdown event so supervisor loop restarts cleanly.
    async def api_server_restart(request: web.Request) -> web.Response:
        _require_api_access(request)
        log.warning("Server restart requested via API")
        shutdown_evt = request.app.get(APP_SHUTDOWN_EVENT)
        if shutdown_evt is not None:
            request.app[APP_RESTART_REQUESTED] = True
            shutdown_evt.set()
        else:
            # Fallback: no supervisor -- hard restart (legacy path)
            import subprocess

            def _do_restart() -> None:
                try:
                    kwargs: dict[str, Any] = {}
                    if sys.platform == "win32":
                        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                    subprocess.Popen([sys.executable] + sys.argv, close_fds=True, **kwargs)
                except (OSError, PermissionError) as exc:
                    log.error("Failed to spawn replacement server: %s", exc)
                os._exit(0)

            asyncio.get_event_loop().call_later(1.5, _do_restart)
        return web.json_response({"ok": True, "message": "Restarting..."})

    app.router.add_post("/api/server/restart", api_server_restart)

    register_core_routes(app, web_dir=web_dir, handlers=locals())
    register_marketplace_catalog_routes(app, require_api_access=_require_api_access)
    register_plugin_hosting_routes(app)
    register_life_manager_routes(app, require_api_access=_require_api_access)
    register_local_project_routes(
        app,
        require_api_access=_require_api_access,
        require_loopback=_require_loopback,
        read_json=_read_json,
    )

    def _build_mutating_route_policy_snapshot() -> dict[str, Any]:
        policies: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for route in app.router.routes():
            method = str(getattr(route, "method", "") or "").upper()
            if method not in {"POST", "PUT", "PATCH", "DELETE"}:
                continue
            resource = getattr(route, "resource", None)
            if resource is None or not hasattr(resource, "get_info"):
                continue
            info = resource.get_info()
            raw_path = info.get("path") or info.get("formatter") or info.get("prefix")
            if not isinstance(raw_path, str) or not raw_path.startswith("/"):
                continue
            sample_path = re.sub(r"\{[^}]+\}", "audit", raw_path)
            key = (method, sample_path)
            if key in seen:
                continue
            seen.add(key)
            if sample_path.startswith("/webhooks/receive/"):
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

    return app

