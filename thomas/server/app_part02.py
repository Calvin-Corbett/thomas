def create_app(config: AppConfig | None = None):
    from aiohttp import web

    if config is None:
        config = load_config()
    try:
        from thomas.core.model_resolution import resolve_effective_model
        from thomas.preferences.store import get_db_path

        resolved_profile, resolved_model_id = resolve_effective_model(
            config,
            env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
            user_id="default",
            db_path=get_db_path(),
        )
        if resolved_profile in config.models:
            config.default_model = resolved_profile
            if resolved_model_id:
                config.models[resolved_profile].model = resolved_model_id
    except Exception:
        pass

    # Validate configuration before use
    validation_errors = config.validate()
    if validation_errors:
        raise ValueError("Configuration validation failed:\n" + "\n".join(validation_errors))

    # AppKey constants imported from thomas.server.app_keys

    app = web.Application(client_max_size=25 * 1024 * 1024)  # 25 MB
    app[APP_CONFIG] = config
    app[APP_TOOLS] = _build_tools(config)
    app[APP_MEMORY] = _build_memory(config)
    try:
        app[APP_SECRETS] = SecretStore(config.memory.root_path / ".thomas")
    except Exception as secret_exc:
        log.warning("SecretStore initialization failed: %s", secret_exc)
        app[APP_SECRETS] = _FallbackSecretStore()
    app[APP_CHAT_AUTOPILOT_LAST_BY_GOAL_LOCK] = asyncio.Lock()
    app[APP_SESSIONS] = {}
    app[APP_SESSION_LOCKS] = OrderedDict()  # LRU-evicted in _session_lock_for
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
    app[APP_SESSION_ACTIVE_RUNS] = set()
    app[APP_SESSION_ACTIVE_RUNS_LOCK] = asyncio.Lock()
    app[APP_RUN_STORE_ENABLED] = False
    app[APP_RUN_STORE_MODULE] = None
    app[APP_ACTION_AUDIT] = None
    app[APP_GUARDRAILS_ENABLED] = False
    app[APP_GUARDED_TOOL_RUNNER] = None
    app[APP_TASK_LEDGER] = None
    app[APP_CHAT_AUTOPILOT_LAST_BY_GOAL] = {}
    app[APP_RUNTIME_GUARD_STATE] = _runtime_guard_boot_state(config)
    app[APP_RUNTIME_GUARD_TASK] = None
    try:
        _runtime_guard_refresh(app)
    except (OSError, KeyError, ValueError) as runtime_guard_exc:
        log.warning("Runtime guard initialization failed: %s", runtime_guard_exc)

    web_dir = _web_dir()
    chat_store_dir = config.memory.root_path / ".thomas" / "chats"
    chat_store_dir.mkdir(parents=True, exist_ok=True)
    chat_store_lock = asyncio.Lock()

    # ── Startup diagnostics: track which features loaded vs failed ──
    _diagnostics: dict[str, bool] = {}
    _boot_start = time.time()
    _diagnostics["runtime_guard"] = bool(app.get(APP_RUNTIME_GUARD_STATE))

    # Optional: durable per-session task ledger.
    try:
        task_ledger_db_path = resolve_task_ledger_db_path(config.memory.root_path)
        app[APP_TASK_LEDGER] = TaskLedgerStore(task_ledger_db_path)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("Task ledger unavailable: %s", e)
        app[APP_TASK_LEDGER] = None
    _diagnostics["task_ledger"] = app.get(APP_TASK_LEDGER) is not None

    # Optional: time-travel run store persistence + endpoints.
    # Keep persistence enabled even if HTTP replay routes fail to register.
    run_store_mod = None
    try:
        from thomas.observability import run_store as _run_store_mod

        _run_store_mod.init_db(config.memory.root_path / ".thomas" / "runs.sqlite3")
        run_store_mod = _run_store_mod
        app[APP_RUN_STORE_ENABLED] = True
        app[APP_RUN_STORE_MODULE] = _run_store_mod
    except (ImportError, ModuleNotFoundError, OSError, RuntimeError) as e:
        log.warning("Run store unavailable (persistence disabled): %s", e)
    _diagnostics["run_store"] = run_store_mod is not None

    if run_store_mod is not None:
        try:
            from thomas.server.routes.runs import register_runs_routes

            register_runs_routes(app, config)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Run store routes unavailable (persistence still enabled): %s", e)

    # Optional: durable action audit trail (tool action lifecycle).
    try:
        from thomas.policy.redact import Redactor
        from thomas.server.audit_log import AuditLog

        action_redactor = Redactor()
        app[APP_ACTION_AUDIT] = AuditLog(
            path=(config.memory.root_path / ".thomas" / "audit.sqlite3"),
            redactor=action_redactor,
        )
    except (ImportError, ModuleNotFoundError, OSError, RuntimeError) as e:
        log.warning("Action audit unavailable: %s", e)
        app[APP_ACTION_AUDIT] = None
    _diagnostics["action_audit"] = app.get(APP_ACTION_AUDIT) is not None

    # Optional: File-change audit log
    try:
        from thomas.server.routes.audit import handle_audit_files, handle_audit_run_files

        audit_db_path = config.memory.root_path / ".thomas" / "file_audit.db"
        _file_audit.init_audit(audit_db_path)

        async def _audit_files_handler(request: web.Request) -> web.Response:
            _require_api_access(request)
            body, status, headers = await handle_audit_files(request)
            return web.Response(body=body, status=status, headers=headers)

        async def _audit_run_files_handler(request: web.Request) -> web.Response:
            _require_api_access(request)
            run_id = request.match_info.get("run_id", "")
            body, status, headers = await handle_audit_run_files(request, run_id)
            return web.Response(body=body, status=status, headers=headers)

        app.router.add_get("/api/audit/files", _audit_files_handler)
        app.router.add_get("/api/audit/runs/{run_id}/files", _audit_run_files_handler)
        log.info("File audit routes registered")
    except (ImportError, ModuleNotFoundError, OSError, RuntimeError) as e:
        log.warning("File audit routes unavailable: %s", e)
        _diagnostics["file_audit"] = False
    else:
        _diagnostics["file_audit"] = True

    # Optional: Guardrails policy + approval API
    try:
        from thomas.agent.approval import ApprovalBroker
        from thomas.agent.guarded_tools import GuardedToolRunner
        from thomas.policy.config import load_policy_config
        from thomas.policy.policy import PolicyEngine
        from thomas.policy.redact import Redactor
        from thomas.server.guardrails_api import install_guardrails_routes

        policy_cfg = load_policy_config(str(config.memory.root_path))
        if "THOMAS_NO_HUMAN_MODE" not in os.environ and "THOMAS_GUARDRAILS_NO_HUMAN_MODE" not in os.environ:
            os.environ["THOMAS_NO_HUMAN_MODE"] = policy_cfg.guardrails.no_human_mode

        # Wire AdvancedToolsPrefs boolean toggles into policy deny_groups.
        try:
            _prefs_store = PreferencesStore(get_db_path())
            _tool_prefs = _prefs_store.get().advanced.tools
            _deny = list(policy_cfg.deny_groups)
            if not _tool_prefs.allow_shell and "shell" not in _deny:
                _deny.append("shell")
            if not _tool_prefs.allow_file_write and "file_write" not in _deny:
                _deny.append("file_write")
            if not _tool_prefs.allow_network and "network" not in _deny:
                _deny.append("network")
            if not _tool_prefs.allow_browser and "browser" not in _deny:
                _deny.append("browser")
            if not _tool_prefs.allow_channels and "channels" not in _deny:
                _deny.append("channels")
            if not _tool_prefs.allow_git and "git" not in _deny:
                _deny.append("git")
            policy_cfg.deny_groups = _deny
        except (AttributeError, KeyError, OSError) as _pe:
            log.debug("Tool prefs -> deny_groups merge skipped: %s", _pe)

        approvals = ApprovalBroker()
        redactor = Redactor(additional_patterns=policy_cfg.redact_additional_patterns)
        audit = app.get(APP_ACTION_AUDIT)

        # Build tool category map from registry for group deny fallback matching.
        _tool_cats: dict = {}
        try:
            for t in app.get(APP_TOOLS) or []:
                tname = getattr(t, "name", "") or ""
                tcat = getattr(t, "category", "") or ""
                if tname and tcat:
                    _tool_cats[tname] = tcat
        except (AttributeError, TypeError):
            pass
        policy = PolicyEngine.from_config(policy_cfg, tool_categories=_tool_cats)
        guarded_runner = GuardedToolRunner(
            policy=policy,
            approvals=approvals,
            redactor=redactor,
            audit=audit,
            approval_timeout_s=policy_cfg.guardrails.approval_timeout_s,
            no_human_mode=policy_cfg.guardrails.no_human_mode,
        )
        install_guardrails_routes(app, approvals)
        app[APP_GUARDRAILS_ENABLED] = bool(policy_cfg.guardrails.enabled)
        app[APP_GUARDED_TOOL_RUNNER] = guarded_runner
        app[APP_APPROVALS_BROKER] = approvals
        app[APP_GUARDRAILS_CTX] = {
            "config": policy_cfg,
            "approvals": approvals,
            "redactor": redactor,
            "audit": audit,
            "policy": policy,
        }
        app["approvals"] = approvals
    except (ImportError, ModuleNotFoundError, RuntimeError, ValueError, OSError) as e:
        log.warning("Guardrails unavailable: %s", e)
    _diagnostics["guardrails"] = app.get(APP_GUARDRAILS_ENABLED, False)

    # Optional: realtime routes
    _realtime_ok = False
    try:
        from thomas.realtime.routes import setup_realtime_routes

        setup_realtime_routes(app, require_api_access=lambda req: _require_api_access(req))
        _realtime_ok = True
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
        log.warning("Realtime routes unavailable: %s", e)
    _diagnostics["realtime"] = _realtime_ok

    # Optional: autonomy engine
    _autonomy_ok = False
    try:
        from thomas.autonomy import install_autonomy

        autonomy_enabled = _env_flag("THOMAS_AUTONOMY_ENABLED", False)
        autonomy_token = os.environ.get("THOMAS_AUTONOMY_TOKEN")
        install_autonomy(app, config, enabled=autonomy_enabled, api_token=autonomy_token)
        _autonomy_ok = True
    except (ImportError, ModuleNotFoundError, RuntimeError, ValueError) as e:
        log.warning("Autonomy engine unavailable: %s", e)
    _diagnostics["autonomy"] = _autonomy_ok

    # Background engines: ALL engines via unified EngineManager
    # One call starts: persistence, tool_factory, initiative, testing_suite
    try:
        from thomas.core.engine_manager import get_engine_manager

        engine_manager = get_engine_manager()
        results = engine_manager.start_all()
        log.info("EngineManager: started all engines - %s", results)

        # Store reference for status endpoint
        app[APP_ENGINE_MANAGER] = engine_manager

    except (ImportError, ModuleNotFoundError, RuntimeError, OSError) as e:
        log.warning("Background engines unavailable: %s", e)
    _diagnostics["engines"] = app.get(APP_ENGINE_MANAGER) is not None

    # ── Store diagnostics + health endpoint ──
    _diagnostics["memory"] = app[APP_MEMORY] is not None
    app[APP_DIAGNOSTICS] = _diagnostics
    app[APP_BOOT_TIME] = time.time()
    app[APP_BOOT_DURATION] = time.time() - _boot_start
    app[APP_CRASH_COUNT] = 0  # updated by supervisor if applicable

    async def api_health(request: web.Request) -> web.Response:
        diag = request.app.get(APP_DIAGNOSTICS, {})
        boot_time = request.app.get(APP_BOOT_TIME, 0)
        degraded = [k for k, v in diag.items() if not v]
        return web.json_response(
            {
                "status": "degraded" if degraded else "ok",
                "version": str(THOMAS_VERSION),
                "uptime_s": round(time.time() - boot_time, 1) if boot_time else 0,
                "pid": os.getpid(),
                "features": diag,
                "degraded": degraded,
                "crash_count": request.app.get(APP_CRASH_COUNT, 0),
            }
        )

    async def api_bootdoctor_recovery_notice(request: web.Request) -> web.Response:
        consume = str(request.query.get("consume", "")).strip().lower() in {"1", "true", "yes"}
        repo_root = Path(__file__).resolve().parents[2]
        notice = read_boot_recovery_notice(repo_root, consume=consume)
        return web.json_response({"notice": notice})

    app.router.add_get("/api/health", api_health)
    app.router.add_get("/healthz", api_health)
    app.router.add_get("/api/bootdoctor/recovery_notice", api_bootdoctor_recovery_notice)

    # Register health readiness check
    from thomas.server.routes.health import register_health_ready_route

    register_health_ready_route(app)

    _security_headers_enabled = _env_flag("THOMAS_SECURITY_HEADERS_ENABLED", True)
    _frame_options = str(os.environ.get("THOMAS_FRAME_OPTIONS", "SAMEORIGIN") or "").strip()
    _security_headers: dict[str, str] = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' blob: https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "img-src 'self' data: blob:; "
            "font-src 'self' https://cdn.jsdelivr.net https://unpkg.com; "
            "connect-src 'self'"
        ),
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-site",
        "X-Permitted-Cross-Domain-Policies": "none",
    }
    if _frame_options:
        _security_headers["X-Frame-Options"] = _frame_options

    # ── Global exception logger ─────────────────────────────────────
    # Must be the FIRST middleware so it wraps everything.  Logs the
    # full traceback for any unhandled exception that would otherwise
    # surface as aiohttp's generic "500 Server got itself in trouble".
    @web.middleware
    async def exception_logger(request: web.Request, handler):  # type: ignore[no-untyped-def]
        try:
            return await handler(request)
        except web.HTTPException:
            raise  # normal HTTP errors (4xx, redirects, etc.) -- pass through
        except asyncio.CancelledError:
            raise  # don't suppress cancellation
        except Exception:  # REVIEWED: broad catch — last-resort error boundary
            log.exception("[thomas] Unhandled exception on %s %s", request.method, request.path)
            raise

    app.middlewares.append(exception_logger)

    @web.middleware
    async def security_headers(request: web.Request, handler):  # type: ignore[no-untyped-def]
        resp = await handler(request)
        if _security_headers_enabled and not bool(getattr(resp, "prepared", False)):
            for header_name, header_value in _security_headers.items():
                resp.headers.setdefault(header_name, header_value)
        return resp

    app.middlewares.append(security_headers)

    @web.middleware
    async def no_cache_ui_assets(request: web.Request, handler):  # type: ignore[no-untyped-def]
        resp = await handler(request)
        cfg = _resolve_runtime_config(app)
        is_prod = bool(getattr(cfg, "is_production", False))

        if request.method == "GET":
            if request.path in {"/", "/mission", "/settings", "/companion", "/landing"}:
                resp.headers.setdefault("Cache-Control", "no-store")
                resp.headers.setdefault("Pragma", "no-cache")
                resp.headers.setdefault("Expires", "0")
            elif request.path.startswith("/static/"):
                if is_prod:
                    resp.headers.setdefault(
                        "Cache-Control",
                        "public, max-age=31536000, immutable",
                    )
                else:
                    resp.headers.setdefault("Cache-Control", "no-store")
                    resp.headers.setdefault("Pragma", "no-cache")
                    resp.headers.setdefault("Expires", "0")
        return resp

    app.middlewares.append(no_cache_ui_assets)

    def _is_loopback_request(request: web.Request) -> bool:
        remote = request.remote or ""
        try:
            ip = ipaddress.ip_address(remote)
            return ip.is_loopback
        except ValueError:
            return False

    def _extract_request_token(request: web.Request) -> str:
        auth = str(request.headers.get("Authorization") or "").strip()
        if auth:
            match = _BEARER_TOKEN_RE.match(auth)
            if not match:
                return ""
            return match.group(1)

        token = str(request.headers.get("X-Api-Token") or "").strip()
        if not token or any(ch.isspace() for ch in token):
            return ""
        return token

    rate_limit_state: dict[str, deque[float]] = {}
    rate_limit_lock = asyncio.Lock()
    rate_limit_gc_at = 0.0

    def _parse_server_int(raw: Any, default: int, minimum: int = 1) -> int:
        try:
            val = int(raw)
        except (ValueError, TypeError):
            val = default
        return max(minimum, val)

    def _remote_rate_limit_key(request: web.Request) -> str:
        token = _extract_request_token(request)
        if token:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
            return f"token:{digest}"
        remote = str(request.remote or "").strip() or "unknown"
        return f"ip:{remote}"

    async def _consume_remote_rate_limit(request: web.Request) -> tuple[bool, int]:
        """Best-effort fixed-window limiter for remote-mode API traffic."""
        nonlocal rate_limit_gc_at
        cfg: AppConfig = _resolve_runtime_config(app)
        srv = getattr(cfg, "server", None)
        max_requests = _parse_server_int(getattr(srv, "rate_limit_max_requests", 120), 120)
        window_s = _parse_server_int(getattr(srv, "rate_limit_window_seconds", 60), 60)

        key = _remote_rate_limit_key(request)
        now = time.monotonic()
        cutoff = now - float(window_s)

        async with rate_limit_lock:
            bucket = rate_limit_state.get(key)
            if bucket is None:
                bucket = deque()
                rate_limit_state[key] = bucket

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= max_requests:
                oldest = bucket[0] if bucket else now
                retry_after = max(1, int(math.ceil(float(window_s) - (now - oldest))))
                return False, retry_after

            bucket.append(now)

            # Opportunistic cleanup to keep state bounded.
            gc_interval = min(max(float(window_s), 5.0), 60.0)
            if (now - rate_limit_gc_at) >= gc_interval:
                stale_before = now - float(window_s)
                stale_keys = [k for k, b in rate_limit_state.items() if (not b) or b[-1] <= stale_before]
                for stale_key in stale_keys:
                    rate_limit_state.pop(stale_key, None)
                rate_limit_gc_at = now

        return True, 0

    @web.middleware
    async def remote_api_rate_limit(request: web.Request, handler):  # type: ignore[no-untyped-def]
        if request.path.startswith("/api/"):
            cfg: AppConfig = _resolve_runtime_config(app)
            srv = getattr(cfg, "server", None)
            mode = str(getattr(srv, "access_mode", "local") or "local").strip().lower()
            enabled = bool(getattr(srv, "rate_limit_enabled", True))
            if mode == "remote" and enabled:
                allowed, retry_after = await _consume_remote_rate_limit(request)
                if not allowed:
                    raise web.HTTPTooManyRequests(
                        text="remote api rate limit exceeded",
                        headers={"Retry-After": str(retry_after)},
                    )
        return await handler(request)

    app.middlewares.append(remote_api_rate_limit)

    # Token bucket rate limiter (configurable via config)
    from thomas.server.middleware.rate_limit import RateLimitStore, create_rate_limit_middleware

    cfg: AppConfig = _resolve_runtime_config(app)
    srv = getattr(cfg, "server", None)
    rate_limit_window = _parse_server_int(getattr(srv, "rate_limit_window_seconds", 60), 60)
    rate_limit_chat = _parse_server_int(getattr(srv, "rate_limit_max_requests", 120), 120)
    # Default: half the general limit for chat endpoints
    rate_limit_chat_default = max(1, rate_limit_chat // 2)

    rate_limit_store = RateLimitStore(window_seconds=rate_limit_window)
    rate_limit_middleware = create_rate_limit_middleware(
        rate_limit_store,
        chat_limit=rate_limit_chat_default,
        general_limit=rate_limit_chat,
        window_seconds=rate_limit_window,
        skip_loopback=True,
    )
    app.middlewares.append(rate_limit_middleware)

    def _require_api_token(request: web.Request) -> None:
        cfg: AppConfig = _resolve_runtime_config(app)
        expected = str(getattr(getattr(cfg, "server", None), "api_token", "") or "").strip()
        if not expected:
            raise web.HTTPUnauthorized(text="server api token is not configured")
        incoming = _extract_request_token(request)
        if not incoming:
            raise web.HTTPUnauthorized(text="missing api token")
        if not hmac.compare_digest(incoming.encode("utf-8"), expected.encode("utf-8")):
            raise web.HTTPUnauthorized(text="invalid api token")

    def _require_loopback(request: web.Request) -> None:
        if not _is_loopback_request(request):
            raise web.HTTPForbidden(text="This endpoint is only available from localhost.")
        _require_same_origin_browser_request(request)

    def _require_api_access(request: web.Request) -> None:
        cfg: AppConfig = _resolve_runtime_config(app)
        mode = str(getattr(getattr(cfg, "server", None), "access_mode", "local") or "local").strip().lower()
        if mode == "remote":
            _require_api_token(request)
            return
        _require_loopback(request)

    def _is_mutating_control_plane_route(request: web.Request) -> bool:
        method = str(request.method or "").upper()
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return False
        path = str(request.path or "")
        if path.startswith("/webhooks/receive/"):
            return False
        return path.startswith("/api/") or path.startswith("/gateway/") or path.startswith("/v1/") or path == "/probe"

    def _is_local_browser_origin_host(host: str) -> bool:
        token = str(host or "").strip().lower()
        if not token:
            return False
        if _is_loopback_host(token):
            return True
        # Android/Genymotion emulator aliases that map back to host loopback.
        return token in {"10.0.2.2", "10.0.3.2"}

    def _require_csrf_guard(request: web.Request) -> None:
        raw_token = str(os.environ.get("THOMAS_MUTATING_CSRF_TOKEN", "") or "").strip()
        if not raw_token:
            return

        provided = str(request.headers.get("X-CSRF-Token") or "").strip()
        if not provided:
            raise web.HTTPForbidden(text="Missing X-CSRF-Token for this mutating request.")
        if not hmac.compare_digest(provided.encode("utf-8"), raw_token.encode("utf-8")):
            raise web.HTTPForbidden(text="Invalid X-CSRF-Token for this request.")

    @web.middleware
    async def csrf_guard_mutating_api(request: web.Request, handler):  # type: ignore[no-untyped-def]
        if _is_mutating_control_plane_route(request):
            _require_csrf_guard(request)
        return await handler(request)

    app.middlewares.append(csrf_guard_mutating_api)

    @web.middleware
    async def authz_guard_mutating_api(request: web.Request, handler):  # type: ignore[no-untyped-def]
        if _is_mutating_control_plane_route(request):
            _require_api_access(request)
        return await handler(request)

    app.middlewares.append(authz_guard_mutating_api)

    def _require_same_origin_browser_request(request: web.Request) -> None:
        """Reject cross-origin browser requests to localhost-only endpoints.

        Browser-based CSRF attempts to localhost services include Origin and/or
        Sec-Fetch-Site headers; reject anything not same-origin.
        """
        fetch_site = str(request.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if fetch_site and fetch_site not in {"same-origin", "none"}:
            raise web.HTTPForbidden(text="Cross-site browser requests are not allowed.")

        raw_origin = str(request.headers.get("Origin") or "").strip()
        if not raw_origin:
            return

        try:
            origin = urlparse(raw_origin)
        except (ValueError, AttributeError):
            raise web.HTTPForbidden(text="Invalid Origin header.")

        if origin.scheme not in ("http", "https") or not origin.hostname:
            raise web.HTTPForbidden(text="Invalid Origin header.")

        origin_host = str(origin.hostname or "").lower()
        if not _is_local_browser_origin_host(origin_host):
            raise web.HTTPForbidden(text="Cross-origin browser requests are not allowed.")

        request_scheme = str(request.url.scheme or "").lower()
        request_host = str(request.url.host or "").lower()
        request_port = int(request.url.port or (443 if request_scheme == "https" else 80))

        origin_scheme = str(origin.scheme or "").lower()
        origin_port = int(origin.port or (443 if origin_scheme == "https" else 80))
        hosts_match = origin_host == request_host
        local_alias_match = _is_local_browser_origin_host(origin_host) and _is_local_browser_origin_host(request_host)

        if origin_scheme != request_scheme or not (hosts_match or local_alias_match) or origin_port != request_port:
            raise web.HTTPForbidden(text="Cross-origin browser requests are not allowed.")

    def _is_json_content_type(request: web.Request) -> bool:
        ctype = str(request.content_type or "").strip().lower()
        return ctype == "application/json" or ctype.endswith("+json")

    async def _read_json(request: web.Request) -> Any:
        """Parse JSON with a couple of real-world robustness tweaks.

        - Some Windows tools write UTF-8 with BOM, which breaks json.loads().
        - Avoid returning 500s on malformed JSON; surface as a 400 instead.
        """
        try:
            raw = await request.read()
        except (OSError, asyncio.TimeoutError) as e:
            raise web.HTTPBadRequest(text=f"invalid json: {type(e).__name__}: {e}")

        if not raw:
            return {}

        if not _is_json_content_type(request):
            raise web.HTTPUnsupportedMediaType(text="content-type must be application/json")

        try:
            text = raw.decode("utf-8-sig")
            return json.loads(text)
        except UnicodeDecodeError as e:
            raise web.HTTPBadRequest(text=f"invalid json: {type(e).__name__}: {e}")
        except json.JSONDecodeError as e:
            raise web.HTTPBadRequest(text=f"invalid json: {e}")

    _SESSION_LOCKS_MAX = 1024  # cap to prevent unbounded memory growth

    async def _session_lock_for(session_id: str) -> asyncio.Lock:
        token = str(session_id or "").strip()
        if not token:
            return asyncio.Lock()
        session_locks = _resolve_app_value(app, APP_SESSION_LOCKS, expected_type=dict, required=True)
        lock = session_locks.get(token)
        if lock is not None:
            session_locks.move_to_end(token)  # LRU refresh
            return lock
        session_locks_lock = _resolve_app_value(app, APP_SESSION_LOCKS_LOCK, required=True)
        async with session_locks_lock:
            session_locks = _resolve_app_value(app, APP_SESSION_LOCKS, expected_type=dict, required=True)
            existing = session_locks.get(token)
            if existing is not None:
                session_locks.move_to_end(token)
                return existing
            created = asyncio.Lock()
            session_locks[token] = created
            # Evict oldest entries that aren't currently held
            while len(session_locks) > _SESSION_LOCKS_MAX:
                oldest_key, oldest_lock = next(iter(session_locks.items()))
                if oldest_lock.locked():
                    break  # don't evict a lock that's in use
                del session_locks[oldest_key]
            return created

    async def _begin_session_run(session_id: str) -> bool:
        token = str(session_id or "").strip()
        if not token:
            return True
        active_runs_lock = _resolve_app_value(app, APP_SESSION_ACTIVE_RUNS_LOCK, required=True)
        async with active_runs_lock:
            active = _resolve_app_value(app, APP_SESSION_ACTIVE_RUNS, expected_type=set, required=True)
            if token in active:
                return False
            active.add(token)
            return True

    async def _end_session_run(session_id: str) -> None:
        token = str(session_id or "").strip()
        if not token:
            return
        active_runs_lock = _resolve_app_value(app, APP_SESSION_ACTIVE_RUNS_LOCK, required=True)
        async with active_runs_lock:
            active = _resolve_app_value(app, APP_SESSION_ACTIVE_RUNS, expected_type=set, required=True)
            active.discard(token)

    def _task_ledger_update(
        session_id: str,
        *,
        active_goal: Any = None,
        status: Any = None,
        missing_inputs: Any = None,
        last_progress: Any = None,
        source: str = "",
        force_event: bool = False,
    ) -> dict[str, Any] | None:
        ledger = app.get(APP_TASK_LEDGER)
        if ledger is None:
            return None
        try:
            snapshot = ledger.update(
                session_id,
                active_goal=active_goal,
                status=status,
                missing_inputs=missing_inputs,
                last_progress=last_progress,
                source=source,
                force_event=force_event,
            )
        except (OSError, RuntimeError, ValueError) as e:
            log.debug("Task ledger update failed (%s): %s", source, e)
            return None
        return snapshot.to_dict()

    # Optional: webhook routes (FastAPI logic bridged into aiohttp handlers)
    try:
        from thomas.server.routes.webhooks_aiohttp import register_webhooks_routes

        register_webhooks_routes(
            app,
            require_api_access=_require_api_access,
            signature_enforcement_default=str(config.server.access_mode or "local").strip().lower() == "remote",
        )
    except (ImportError, ModuleNotFoundError, RuntimeError, AttributeError) as e:
        log.warning("Webhook routes unavailable: %s", e)

    def _join_url(base: str, path: str) -> str:
        b = (base or "").rstrip("/")
        p = path or ""
        if not p.startswith("/"):
            p = "/" + p
        return b + p

    def _is_loopback_host(host: str) -> bool:
        if not host:
            return False
        if host.lower() in ("localhost", "127.0.0.1", "::1"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def _ollama_base_url(profile: str = "local") -> str:
        cfg: AppConfig = _resolve_runtime_config(app)
        if profile not in cfg.models:
            raise web.HTTPBadRequest(text=f"unknown profile: {profile}")
        base = str(cfg.models[profile].base_url or "").strip()
        if not base:
            raise web.HTTPBadRequest(text=f"models.{profile}.base_url is empty")
        base = base.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        u = urlparse(base)
        if u.scheme not in ("http", "https"):
            raise web.HTTPBadRequest(text="local model base_url must be http(s)")
        if not _is_loopback_host(u.hostname or ""):
            raise web.HTTPBadRequest(text="local model base_url must be loopback (localhost/127.0.0.1)")
        return base

    def _model_cfg_with_secrets(profile: str):
        cfg: AppConfig = _resolve_runtime_config(app)
        base = cfg.get_model(profile)
        secrets: SecretStore = _resolve_app_value(app, APP_SECRETS, required=True)
        key = secrets.get(profile)
        if key:
            base = replace(base, api_key=key)
        return base

    def _failover_cfgs_with_secrets(primary_profile: str):
        cfg: AppConfig = _resolve_runtime_config(app)
        out: list[Any] = []
        for fb in cfg.failover_chain(primary_profile):
            try:
                out.append(_model_cfg_with_secrets(fb.name))
            except (KeyError, AttributeError, ValueError) as e:
                log.debug("Skipping failover profile %s: %s", getattr(fb, "name", "?"), e)
        return out

    async def _resolve_natural_model_switch_request(
        text: str,
        *,
        current_profile: str,
    ):
        if not is_model_switch_request(text):
            return None

        cfg: AppConfig = _resolve_runtime_config(app)
        default_models = {
            str(name): str(getattr(model_cfg, "model", "") or "").strip() for name, model_cfg in cfg.models.items()
        }
        candidate_profiles = infer_profile_candidates(
            text,
            current_profile=current_profile,
            available_profiles=default_models.keys(),
        )
        discovered: dict[str, list[str]] = {}
        for profile_name in candidate_profiles[:6]:
            profile_name = str(profile_name or "").strip()
            if not profile_name or profile_name not in cfg.models:
                continue
            ids: list[str] = []
            default_id = default_models.get(profile_name, "")
            if default_id:
                ids.append(default_id)
            try:
                hs = await handshake_models_async(_model_cfg_with_secrets(profile_name), timeout_s=2.5)
                for mid in list(hs.models or []):
                    m = str(mid or "").strip()
                    if m and m not in ids:
                        ids.append(m)
            except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as e:
                log.debug("Model switch discovery failed for profile %s: %s", profile_name, e)
            discovered[profile_name] = ids

        return resolve_model_switch_request(
            text,
            current_profile=current_profile,
            default_models=default_models,
            discovered_models=discovered,
        )

    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return int(default)

    def _clone_json(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _chat_file_for(chat_id: str) -> Path:
        digest = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()
        return chat_store_dir / f"{digest}.json"

    def _sanitize_chat_payload(payload: Any, *, chat_id: str | None = None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="chat payload must be a JSON object")

        requested_id = str(payload.get("id") or "").strip()
        resolved_id = str(chat_id or requested_id).strip()
        if not resolved_id:
            raise web.HTTPBadRequest(text="missing chat id")
        if len(resolved_id) > 160:
            raise web.HTTPBadRequest(text="chat id is too long")
        if requested_id and requested_id != resolved_id:
            raise web.HTTPBadRequest(text="chat id mismatch")

        now_ms = int(time.time() * 1000)
        created_at = _safe_int(payload.get("createdAt"), now_ms)
        updated_at = _safe_int(payload.get("updatedAt"), now_ms)
        updated_at = max(updated_at, created_at)

        title = str(payload.get("title") or "New Chat").strip() or "New Chat"
        if len(title) > 200:
            title = title[:200]

        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            raise web.HTTPBadRequest(text="messages must be a list")

        messages: list[dict[str, Any]] = []
        for msg in raw_messages[:2000]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip()
            if role not in ("user", "assistant"):
                continue

            entry: dict[str, Any] = {
                "id": str(msg.get("id") or secrets.token_urlsafe(8)),
                "role": role,
                "createdAt": _safe_int(msg.get("createdAt"), now_ms),
                "status": str(msg.get("status") or "complete").strip() or "complete",
            }

            content = msg.get("content", "")
            if isinstance(content, str):
                entry["content"] = content[:200_000]
            else:
                try:
                    entry["content"] = _clone_json(content)
                except (json.JSONDecodeError, TypeError, ValueError):
                    entry["content"] = ""

            tool_calls = msg.get("toolCalls")
            if isinstance(tool_calls, list):
                tc_out: list[dict[str, Any]] = []
                for tc in tool_calls[:200]:
                    if not isinstance(tc, dict):
                        continue
                    try:
                        tc_out.append(_clone_json(tc))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                entry["toolCalls"] = tc_out
            else:
                entry["toolCalls"] = []

            meta = msg.get("meta")
            if isinstance(meta, dict):
                try:
                    entry["meta"] = _clone_json(meta)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

            messages.append(entry)

        session_id = payload.get("sessionId")
        if session_id is None:
            safe_session_id = None
        else:
            safe_session_id = str(session_id).strip() or None
            if safe_session_id and len(safe_session_id) > 512:
                safe_session_id = safe_session_id[:512]

        chat = {
            "id": resolved_id,
            "title": title,
            "model": str(payload.get("model") or payload.get("profile") or "").strip() or None,
            "messages": messages,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "pinned": bool(payload.get("pinned", False)),
            "sessionId": safe_session_id,
        }

        encoded = json.dumps(chat, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 10_000_000:
            raise web.HTTPBadRequest(text="chat payload too large")
        return chat

    def _read_chat_from_disk(path: Path) -> dict[str, Any] | None:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            raw_id = str(payload.get("id") or "").strip()
            if not raw_id:
                return None
            return _sanitize_chat_payload(payload, chat_id=raw_id)
