"""Middleware, security handlers, and helper functions for app_core."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from thomas.core.config import AppConfig
from thomas.server.app_keys import (
    APP_DELIVERABLE_PREVIEW_SERVICE,
    APP_SECRETS,
    APP_SESSION_ACTIVE_RUNS,
    APP_SESSION_ACTIVE_RUNS_LOCK,
    APP_SESSION_LOCKS,
    APP_SESSION_LOCKS_LOCK,
    APP_TASK_LEDGER,
)

# Cookie the deliverable preview origin sets per capability. Named here because
# this server has to recognise them as not its own; see the drain middleware.
_PREVIEW_COOKIE_PREFIX = "thomas_preview_"
from thomas.server.app_middleware_security import (
    _BEARER_TOKEN_RE as _BEARER_TOKEN_RE,
)
from thomas.server.app_middleware_security import (
    _is_generated_artifact_asset_request,
    cors_origin_for_request,
    resource_policy_for_request,
    security_headers_config,
)
from thomas.server.app_middleware_security import (
    _is_sandboxed_artifact_asset_request as _is_sandboxed_artifact_asset_request,
)

from .app_helpers import _resolve_runtime_config

if TYPE_CHECKING:
    from aiohttp import web

log = logging.getLogger(__name__)


def setup_middleware_and_handlers(
    app: Any,
    config: AppConfig,
    web_dir: Path,
    chat_store_dir: Path,
    chat_store_lock: asyncio.Lock,
) -> None:
    """Setup all middleware, security handlers, and helper functions."""
    from aiohttp import web

    _security_headers_enabled, _security_headers = security_headers_config()

    @web.middleware
    async def exception_logger(request: web.Request, handler):  # type: ignore[no-untyped-def]
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[thomas] Unhandled exception on %s %s", request.method, request.path)
            raise

    app.middlewares.append(exception_logger)

    @web.middleware
    async def security_headers(request: web.Request, handler):  # type: ignore[no-untyped-def]
        resp = await handler(request)
        if _security_headers_enabled and not bool(getattr(resp, "prepared", False)):
            for header_name, header_value in _security_headers.items():
                resp.headers.setdefault(header_name, header_value)
            # Generated Code previews are multi-file (index.html + styles.css +
            # src/*.js). On a bare-IP host like 127.0.0.1 there is no
            # registrable "site", so Cross-Origin-Resource-Policy: same-site makes
            # Chromium block those same-origin sub-resources as NotSameSite — the app
            # loads index.html but its stylesheet and scripts are refused, rendering a
            # blank/white page. Serve generated-app assets with a CORP that does not
            # depend on the same-site computation so multi-file apps actually render.
            resp.headers["Cross-Origin-Resource-Policy"] = resource_policy_for_request(request)
            allowed_origin = cors_origin_for_request(request)
            if allowed_origin is not None:
                resp.headers["Access-Control-Allow-Origin"] = allowed_origin
        return resp

    app.middlewares.append(security_headers)

    # Deliverable previews run on their own ephemeral 127.0.0.1 port and set one
    # capability cookie each. Cookies carry no port, so every one of those is
    # also sent HERE, where it means nothing -- and they last an hour. Enough of
    # them (about 115, at 69 bytes each) overflow aiohttp's 8190-byte header
    # limit and this server starts refusing every request with a 400 before any
    # handler runs, which reads as the app being broken with no way back except
    # waiting them out or clearing cookies by hand. Observed for real while
    # exercising the project library.
    #
    # This server never needs one, so receiving one means it leaked. Expire it.
    # Draining them here also recovers a browser that has already filled up,
    # which nothing else can do: the preview server cannot reach this origin's
    # cookie jar, and the user has no obvious way to.
    @web.middleware
    async def drain_stray_preview_cookies(request: web.Request, handler):  # type: ignore[no-untyped-def]
        resp = await handler(request)
        names = [name for name in request.cookies if name.startswith(_PREVIEW_COOKIE_PREFIX)]
        if not names or bool(getattr(resp, "prepared", False)):
            return resp
        service = request.app.get(APP_DELIVERABLE_PREVIEW_SERVICE)
        stray = []
        for name in names:
            capability = name[len(_PREVIEW_COOKIE_PREFIX) :]
            # A capability that is still granted belongs to a preview that may
            # yet fetch its stylesheet or script. Expiring that mid-load would
            # break multi-file apps, so only dead ones are swept.
            if service is not None and service.is_live_capability(capability):
                continue
            stray.append(name)
        for name in stray[:64]:  # bounded: the reply must not blow the budget itself
            resp.del_cookie(name, path="/")
        return resp

    app.middlewares.append(drain_stray_preview_cookies)

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
            # In production + remote mode, rate limiting is mandatory.
            if mode == "remote" and cfg.is_production and not enabled:
                log.warning(
                    "Rate limiting was disabled but is mandatory in production+remote mode. Forcing rate limiting ON."
                )
                enabled = True
            if mode == "remote" and enabled:
                allowed, retry_after = await _consume_remote_rate_limit(request)
                if not allowed:
                    raise web.HTTPTooManyRequests(
                        text="remote api rate limit exceeded",
                        headers={"Retry-After": str(retry_after)},
                    )
        return await handler(request)

    app.middlewares.append(remote_api_rate_limit)

    from thomas.server.middleware.rate_limit import RateLimitStore, create_rate_limit_middleware

    cfg: AppConfig = _resolve_runtime_config(app)
    srv = getattr(cfg, "server", None)
    rate_limit_window = _parse_server_int(getattr(srv, "rate_limit_window_seconds", 60), 60)
    rate_limit_chat = _parse_server_int(getattr(srv, "rate_limit_max_requests", 120), 120)
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

    def _is_loopback_host(host: str) -> bool:
        token = str(host or "").strip().lower()
        if not token:
            return False
        # RFC 6761 reserves these to always resolve to loopback, so they are
        # same-machine origins (see tests/test_origin_guard_localhost.py).
        if token == "localhost" or token.endswith(".localhost"):
            return True
        try:
            ip = ipaddress.ip_address(token)
            return ip.is_loopback
        except ValueError:
            return False

    def _require_same_origin_browser_request(request: web.Request) -> None:
        """Reject cross-origin browser requests to localhost-only endpoints."""
        fetch_site = str(request.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if (
            fetch_site
            and fetch_site not in {"same-origin", "none"}
            and not _is_generated_artifact_asset_request(request)
        ):
            raise web.HTTPForbidden(text="Cross-site browser requests are not allowed.")

        raw_origin = str(request.headers.get("Origin") or "").strip()
        if not raw_origin:
            return
        if cors_origin_for_request(request) is not None:
            return

        try:
            origin = urlparse(raw_origin)
        except (ValueError, AttributeError) as e:
            raise web.HTTPForbidden(text="Invalid Origin header.") from e

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

    # Export the access check so app_core.py (audit handlers, realtime lambda) can use
    # it without depending on closure scope. Reads back via app[APP_REQUIRE_API_ACCESS].
    from thomas.server.app_keys import APP_REQUIRE_API_ACCESS

    app[APP_REQUIRE_API_ACCESS] = _require_api_access

    def _is_mutating_control_plane_route(request: web.Request) -> bool:
        method = str(request.method or "").upper()
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return False
        path = str(request.path or "")
        if path.startswith("/webhooks/receive/"):
            return False
        return (
            path.startswith("/api/")
            or path.startswith("/gateway/")
            or path.startswith("/openai-compat/")
            or path.startswith("/v1/")
            or path == "/probe"
        )

    def _is_local_browser_origin_host(host: str) -> bool:
        token = str(host or "").strip().lower()
        if not token:
            return False
        if _is_loopback_host(token):
            return True
        return token in {"10.0.2.2", "10.0.3.2"}

    def _require_csrf_guard(request: web.Request) -> None:
        raw_token = str(os.environ.get("THOMAS_MUTATING_CSRF_TOKEN", "") or "").strip()
        if not raw_token:
            # In production + remote mode, CSRF protection is mandatory.
            cfg_inner: AppConfig = _resolve_runtime_config(app)
            srv_inner = getattr(cfg_inner, "server", None)
            mode_inner = str(getattr(srv_inner, "access_mode", "local") or "local").strip().lower()
            if cfg_inner.is_production and mode_inner == "remote":
                raise web.HTTPForbidden(
                    text="THOMAS_MUTATING_CSRF_TOKEN must be set in production+remote mode. "
                    "Set this environment variable to a strong random token."
                )
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

    def _is_json_content_type(request: web.Request) -> bool:
        ctype = str(request.content_type or "").strip().lower()
        return ctype == "application/json" or ctype.endswith("+json")

    async def _read_json(request: web.Request) -> Any:
        """Parse JSON with robustness tweaks.

        - Some Windows tools write UTF-8 with BOM, which breaks json.loads().
        - Avoid returning 500s on malformed JSON; surface as a 400 instead.
        """
        try:
            raw = await request.read()
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            if not raw:
                raise web.HTTPBadRequest(text="empty request body")
            return json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            # Log the parse detail server-side; return a generic client message so
            # exception text is not exposed to the caller (py/stack-trace-exposure).
            log.debug("Rejected malformed JSON request body: %s", e)
            raise web.HTTPBadRequest(text="malformed json") from e
        except UnicodeDecodeError as e:
            log.debug("Rejected request body with invalid encoding: %s", e)
            raise web.HTTPBadRequest(text="invalid encoding") from e

    async def _session_lock_for(session_id: str) -> asyncio.Lock:
        """Get or create a lock for a session ID, with LRU eviction of old locks."""
        async with app[APP_SESSION_LOCKS_LOCK]:
            locks = app[APP_SESSION_LOCKS]
            if session_id not in locks:
                if len(locks) >= 1000:
                    locks.popitem(last=False)
                locks[session_id] = asyncio.Lock()
            locks.move_to_end(session_id)
            return locks[session_id]

    async def _begin_session_run(session_id: str) -> bool:
        """Mark a session as having an active run."""
        async with app[APP_SESSION_ACTIVE_RUNS_LOCK]:
            if session_id in app[APP_SESSION_ACTIVE_RUNS]:
                return False
            app[APP_SESSION_ACTIVE_RUNS].add(session_id)
        return True

    async def _end_session_run(session_id: str) -> None:
        """Mark a session as no longer running."""
        async with app[APP_SESSION_ACTIVE_RUNS_LOCK]:
            app[APP_SESSION_ACTIVE_RUNS].discard(session_id)

    def _task_ledger_update(
        session_id: str,
        goal: str | None = None,
        status: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Update task ledger with either the legacy or structured route contract."""
        try:
            ledger = app.get(APP_TASK_LEDGER)
            if not ledger:
                return
            if hasattr(ledger, "update"):
                ledger.update(
                    session_id,
                    active_goal=kwargs.get("active_goal", goal),
                    status=status,
                    missing_inputs=kwargs.get("missing_inputs"),
                    last_progress=kwargs.get("last_progress"),
                    source=str(kwargs.get("source") or ""),
                    force_event=bool(kwargs.get("force_event", False)),
                )
                return
            if hasattr(ledger, "update_session_goal"):
                ledger.update_session_goal(session_id, goal or "", status or "in_progress")
        except (AttributeError, KeyError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as e:
            log.debug("Task ledger update failed: %s", e)

    def _join_url(base: str, path: str) -> str:
        base = str(base or "").rstrip("/")
        path = str(path or "").lstrip("/")
        return f"{base}/{path}" if base and path else (base or path)

    def _model_cfg_with_secrets(config: AppConfig, profile: str, model_cfg: Any) -> Any:
        """Resolve model config with embedded secrets."""
        from dataclasses import replace

        if not model_cfg:
            return None
        cfg_copy = replace(model_cfg)
        secret_store = app.get(APP_SECRETS)
        if secret_store and hasattr(cfg_copy, "api_key_secret_name"):
            secret_name = str(cfg_copy.api_key_secret_name or "").strip()
            if secret_name:
                api_key = secret_store.get(secret_name)
                if api_key:
                    cfg_copy.api_key = api_key
        if (
            secret_store
            and str(getattr(cfg_copy, "provider", "") or "").strip().lower().replace("-", "_") == "openai_codex"
        ):
            try:
                from thomas.server.openai_codex_oauth import access_token_from_store, has_openai_codex_token

                access_token = access_token_from_store(secret_store, str(profile or cfg_copy.name or "chatgpt"))
                if access_token:
                    cfg_copy.api_key = access_token
                cfg_copy._openai_codex_token_ready = bool(
                    access_token or has_openai_codex_token(secret_store, str(profile or cfg_copy.name or "chatgpt"))
                )
            except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as e:
                log.debug("Failed to resolve ChatGPT OAuth token for %s: %s", profile, e)
        return cfg_copy

    def _failover_cfgs_with_secrets(config: AppConfig, profile: str) -> list[Any]:
        """Resolve failover configs with embedded secrets."""
        from dataclasses import replace

        prof_cfg = config.models.get(profile)
        if not prof_cfg:
            return []
        failover_list = getattr(prof_cfg, "failover_models", []) or []
        result = []
        secret_store = app.get(APP_SECRETS)
        for fcfg in failover_list:
            if not fcfg:
                continue
            fcfg_copy = replace(fcfg)
            if secret_store and hasattr(fcfg_copy, "api_key_secret_name"):
                secret_name = str(fcfg_copy.api_key_secret_name or "").strip()
                if secret_name:
                    api_key = secret_store.get(secret_name)
                    if api_key:
                        fcfg_copy.api_key = api_key
            if (
                secret_store
                and str(getattr(fcfg_copy, "provider", "") or "").strip().lower().replace("-", "_") == "openai_codex"
            ):
                try:
                    from thomas.server.openai_codex_oauth import access_token_from_store, has_openai_codex_token

                    profile_name = str(getattr(fcfg_copy, "name", "") or "chatgpt")
                    access_token = access_token_from_store(secret_store, profile_name)
                    if access_token:
                        fcfg_copy.api_key = access_token
                    fcfg_copy._openai_codex_token_ready = bool(
                        access_token or has_openai_codex_token(secret_store, profile_name)
                    )
                except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as e:
                    log.debug("Failed to resolve ChatGPT OAuth failover token for %s: %s", fcfg_copy.name, e)
            result.append(fcfg_copy)
        return result

    from .app_chat_store import build_chat_store

    _chat_store = build_chat_store(chat_store_dir, chat_store_lock)
    _chat_file_for = _chat_store["_chat_file_for"]
    _sanitize_chat_payload = _chat_store["_sanitize_chat_payload"]
    _read_chat_from_disk = _chat_store["_read_chat_from_disk"]
    _save_chat_to_disk = _chat_store["_save_chat_to_disk"]
    _delete_chat_from_disk = _chat_store["_delete_chat_from_disk"]
    _load_all_chats_from_disk = _chat_store["_load_all_chats_from_disk"]

    def _web_build_fingerprint(*relative_paths: str) -> str:
        # Cache-busting build fingerprint over file mtime/size only -- not a
        # security primitive, so sha1 is acceptable here (py/weak-sensitive-data-hashing).
        #
        # Hash the explicitly-named files PLUS every JS module and stylesheet.
        # Previously only the few named files were fingerprinted, so a fix to any
        # other runtime/NNN_*.js module or a .css file left the ?v= UNCHANGED -- and
        # browsers kept serving the cached, pre-fix frontend. That is the root cause
        # of "the AI fixed it but it's still broken on my machine": the server had the
        # new code, the browser never re-fetched it. Covering the whole frontend means
        # ANY frontend edit busts the cache. NOTE: we walk all of js/ (not just
        # js/runtime/) so top-level modules like js/composer_redesign.js — loaded
        # directly from index.html with ?v=__THOMAS_WEB_BUILD__ — also bust the cache.
        digest = hashlib.sha1(usedforsecurity=False)
        paths: list[str] = list(relative_paths)
        try:
            for sub, pattern in (("js", "*.js"), ("css", "*.css")):
                base = web_dir / sub
                if base.is_dir():
                    for found in sorted(base.rglob(pattern)):
                        if found.is_file():
                            paths.append(found.relative_to(web_dir).as_posix())
        except OSError:
            pass
        for relative in dict.fromkeys(paths):  # dedupe, preserve order, deterministic
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

    from .app_middleware_helpers import build_page_handlers

    _page_handlers = build_page_handlers(web_dir, _web_build_fingerprint)
    index = _page_handlers["index"]
    classic = _page_handlers["classic"]
    settings = _page_handlers["settings"]
    companion = _page_handlers["companion"]
    landing = _page_handlers["landing"]

    from .app_routes_init import _setup_routes_and_handlers

    _setup_routes_and_handlers(
        app,
        config,
        web_dir,
        chat_store_dir,
        chat_store_lock,
        locals_dict={
            "_require_api_access": _require_api_access,
            "_require_loopback": _require_loopback,
            "_is_json_content_type": _is_json_content_type,
            "_read_json": _read_json,
            "_sanitize_chat_payload": _sanitize_chat_payload,
            "_save_chat_to_disk": _save_chat_to_disk,
            "_delete_chat_from_disk": _delete_chat_from_disk,
            "_load_all_chats_from_disk": _load_all_chats_from_disk,
            "_session_lock_for": _session_lock_for,
            "_begin_session_run": _begin_session_run,
            "_end_session_run": _end_session_run,
            "_task_ledger_update": _task_ledger_update,
            "_model_cfg_with_secrets": _model_cfg_with_secrets,
            "_failover_cfgs_with_secrets": _failover_cfgs_with_secrets,
            "_chat_file_for": _chat_file_for,
            "_read_chat_from_disk": _read_chat_from_disk,
            "_build_tools": __import__("thomas.server.app_helpers", fromlist=["_build_tools"])._build_tools,
            "_web_build_fingerprint": _web_build_fingerprint,
            "index": index,
            "classic": classic,
            "settings": settings,
            "companion": companion,
            "landing": landing,
        },
    )
