"""Thomas HTTP server and lightweight web UI.

This server is intentionally simple:
- Serves static UI from thomas/server/web/
- Exposes a small JSON/NDJSON API for chat + model listing

Install:
  pip install -e ".[server]"

Run:
  thomas serve --port 8899
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import ipaddress
import json
import logging
import math
import os
import shutil
import secrets
import subprocess
import sys
import time
from collections import deque
from urllib.parse import urlparse
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from thomas import __version__ as THOMAS_VERSION
from thomas.agent.loop import AgentLoop
from thomas.core.autonomy import clamp_autonomy_level, autonomy_level_name
from thomas.core.config import AppConfig, load_config
from thomas.core.events import EventType
from thomas.core.llm import LLMClient
from thomas.core.token_economy import (
    apply_token_economy_policy,
    build_token_economy_meta,
)
from thomas.core.rules_of_road import evaluate_rules
from thomas.models.batching import (
    OpenAICompatBatchClient,
    build_completion_request,
    parse_batch_state,
    extract_batch_results,
    extract_result_request_id,
    extract_result_error,
    extract_result_text,
)
from thomas.models.capabilities import supports as model_supports
from thomas.models.chat_controls import resolve_ui_control_request
from thomas.models.discovery import discover_models_async, handshake_models_async
from thomas.models.protocol import validate_model_profile_async
from thomas.models.switching import infer_profile_candidates, is_model_switch_request, resolve_model_switch_request
from thomas.server.chat_batch_mode import BatchModeDeps, handle_batch_mode_chat
from thomas.server.chat_control_mode import ChatControlDeps, handle_ui_control_chat
from thomas.server.secrets import SecretStore
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.git import register_git_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.shell import register_shell_tools
from thomas.observability.journal import TaskJournal, journal_skip_reason
from thomas.observability import file_audit as _file_audit

log = logging.getLogger(__name__)

try:
    from thomas.memory.autonomy import AutonomyMemoryEngine
except Exception:  # pragma: no cover
    AutonomyMemoryEngine = None  # type: ignore[assignment]


@dataclass
class ChatSession:
    id: str
    conversation: List[Dict[str, Any]]
    profile: str
    model_id: Optional[str] = None
    autonomy_level: int = 3
    system_prompt: Optional[str] = None

def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_usage_payload(payload: Any) -> Dict[str, int]:
    """Normalize usage object/dict to {prompt_tokens, completion_tokens, total_tokens}."""
    if isinstance(payload, dict):
        prompt_raw = payload.get("prompt_tokens", 0)
        completion_raw = payload.get("completion_tokens", 0)
        total_raw = payload.get("total_tokens", 0)
    else:
        prompt_raw = getattr(payload, "prompt_tokens", 0)
        completion_raw = getattr(payload, "completion_tokens", 0)
        total_raw = getattr(payload, "total_tokens", 0)

    try:
        prompt = max(0, int(prompt_raw or 0))
    except Exception:
        prompt = 0
    try:
        completion = max(0, int(completion_raw or 0))
    except Exception:
        completion = 0
    try:
        total = max(0, int(total_raw or 0))
    except Exception:
        total = 0
    total = max(total, prompt + completion)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _swarm_tool_mutates_fs(name: str, _args: Dict[str, Any]) -> bool:
    n = (name or "").lower()
    return any(
        k in n
        for k in (
            "fs.",
            "diff.",
            "git.",
            "shell",
            "write",
            "edit",
            "delete",
            "remove",
            "rename",
            "mkdir",
            "rmdir",
            "move",
            "copy",
            "apply",
            "patch",
        )
    )


class _LLMSwarmSubagent:
    """Basic LLM-backed Swarm subagent for planner/coder/tester/reviewer roles."""

    def __init__(
        self,
        agent_id: str,
        model_cfg,
        system_hint: str,
        *,
        fallback_cfgs: Optional[List[Any]] = None,
        failover_enabled: bool = False,
        failover_cooldown_s: int = 300,
        failover_on_auth_error: bool = False,
    ):
        self.agent_id = agent_id
        self._model_cfg = model_cfg
        self._system_hint = system_hint
        self._fallback_cfgs = list(fallback_cfgs or [])
        self._failover_enabled = bool(failover_enabled)
        self._failover_cooldown_s = int(failover_cooldown_s)
        self._failover_on_auth_error = bool(failover_on_auth_error)

    async def run_task(
        self,
        *,
        task,
        graph,
        prior_results,
        emit_text,
        call_tool,
        cancel_event,
    ):
        from thomas.agent.swarm import TaskResult

        llm = LLMClient(
            self._model_cfg,
            fallback_configs=self._fallback_cfgs,
            failover_enabled=self._failover_enabled,
            failover_cooldown_s=self._failover_cooldown_s,
            failover_on_auth_error=self._failover_on_auth_error,
        )
        chunks: List[str] = []
        try:
            prior_bits: List[str] = []
            for tid, tr in (prior_results or {}).items():
                txt = (getattr(tr, "output", "") or "").strip()
                if not txt:
                    continue
                prior_bits.append(f"[{tid}] {txt[:500]}")
            prior_blob = "\n".join(prior_bits[:10]).strip()

            user_prompt = (
                f"Task ID: {task.id}\n"
                f"Task title: {task.title}\n"
                f"Task prompt:\n{task.prompt}\n\n"
            )
            if getattr(task, "acceptance", None):
                user_prompt += "Acceptance:\n" + "\n".join(f"- {x}" for x in task.acceptance) + "\n\n"
            if prior_blob:
                user_prompt += "Prior task outputs:\n" + prior_blob + "\n"

            messages = [
                {"role": "system", "content": self._system_hint},
                {"role": "user", "content": user_prompt},
            ]

            async for ev in llm.stream_chat(messages, tools=None):
                if cancel_event.is_set():
                    return TaskResult(ok=False, error="cancelled", output="".join(chunks))
                if ev.type == "token":
                    t = str(ev.data.get("text", ""))
                    if t:
                        chunks.append(t)
                        await emit_text(t)
                elif ev.type == "error":
                    return TaskResult(ok=False, error=str(ev.data.get("error") or "llm error"), output="".join(chunks))

            return TaskResult(ok=True, output="".join(chunks).strip())
        except Exception as e:
            return TaskResult(ok=False, error=f"{type(e).__name__}: {e}", output="".join(chunks))
        finally:
            await llm.close()


def _build_tools(config: AppConfig) -> ToolRegistry:
    registry = ToolRegistry()
    sandbox = config.tools.sandbox_path
    register_filesystem_tools(registry, sandbox, config.tools.max_file_size)
    if config.tools.allow_shell:
        register_shell_tools(
            registry,
            sandbox,
            config_timeout=config.tools.shell_timeout,
            allowed=True,
        )
    register_git_tools(registry, sandbox)
    register_code_search_tools(registry, sandbox)
    register_diff_tools(registry, sandbox)
    return registry


def _build_memory(config: AppConfig):
    if AutonomyMemoryEngine is None:
        return None
    try:
        engine = AutonomyMemoryEngine(
            config,
            enable_v2=_env_flag("THOMAS_MEMORY_V2_ENABLED", True),
            enable_legacy=True,
        )
        engine.start()
        return engine
    except Exception as e:
        log.warning("Memory engine failed to start: %s", e)
        return None


def _web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def create_app(config: Optional[AppConfig] = None):
    from aiohttp import web

    if config is None:
        config = load_config()

    APP_CONFIG = web.AppKey("config", AppConfig)
    APP_TOOLS = web.AppKey("tools", ToolRegistry)
    APP_MEMORY = web.AppKey("memory", object)
    APP_SECRETS = web.AppKey("secrets", SecretStore)
    APP_SESSIONS = web.AppKey("sessions", dict)
    APP_RUN_STORE_ENABLED = web.AppKey("run_store_enabled", bool)
    APP_RUN_STORE_MODULE = web.AppKey("run_store_module", object)
    APP_GUARDRAILS_ENABLED = web.AppKey("guardrails_enabled", bool)
    APP_GUARDED_TOOL_RUNNER = web.AppKey("guarded_tool_runner", object)
    APP_GUARDRAILS_CTX = web.AppKey("guardrails_ctx", dict)
    APP_CODEX_BRIDGE = web.AppKey("_codex_bridge", object)
    APP_ENGINE_MANAGER = web.AppKey("engine_manager", object)

    app = web.Application(client_max_size=25 * 1024 * 1024)  # 25 MB
    app[APP_CONFIG] = config
    app[APP_TOOLS] = _build_tools(config)
    app[APP_MEMORY] = _build_memory(config)
    app[APP_SECRETS] = SecretStore(config.memory.root_path / ".thomas")
    app[APP_SESSIONS] = {}
    app[APP_RUN_STORE_ENABLED] = False
    app[APP_RUN_STORE_MODULE] = None
    app[APP_GUARDRAILS_ENABLED] = False
    app[APP_GUARDED_TOOL_RUNNER] = None

    web_dir = _web_dir()
    chat_store_dir = config.memory.root_path / ".thomas" / "chats"
    chat_store_dir.mkdir(parents=True, exist_ok=True)
    chat_store_lock = asyncio.Lock()

    # Optional: time-travel run store persistence + endpoints.
    # Keep persistence enabled even if HTTP replay routes fail to register.
    run_store_mod = None
    try:
        from thomas.observability import run_store as _run_store_mod

        _run_store_mod.init_db(config.memory.root_path / ".thomas" / "runs.sqlite3")
        run_store_mod = _run_store_mod
        app[APP_RUN_STORE_ENABLED] = True
        app[APP_RUN_STORE_MODULE] = _run_store_mod
    except Exception as e:
        log.warning("Run store unavailable (persistence disabled): %s", e)

    if run_store_mod is not None:
        try:
            from thomas.server.routes.runs import register_runs_routes

            register_runs_routes(app, config)
        except Exception as e:
            log.warning("Run store routes unavailable (persistence still enabled): %s", e)

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
    except Exception as e:
        log.warning("File audit routes unavailable: %s", e)

    # Optional: Guardrails policy + approval API
    try:
        from thomas.agent.approval import ApprovalBroker
        from thomas.agent.guarded_tools import GuardedToolRunner
        from thomas.policy.config import load_policy_config
        from thomas.policy.policy import PolicyEngine
        from thomas.policy.redact import Redactor
        from thomas.server.audit_log import AuditLog
        from thomas.server.guardrails_api import install_guardrails_routes

        policy_cfg = load_policy_config(str(config.memory.root_path))
        approvals = ApprovalBroker()
        redactor = Redactor(additional_patterns=policy_cfg.redact_additional_patterns)
        audit = AuditLog(path=(config.memory.root_path / ".thomas" / "audit.sqlite3"), redactor=redactor)
        policy = PolicyEngine.from_config(policy_cfg)
        guarded_runner = GuardedToolRunner(
            policy=policy,
            approvals=approvals,
            redactor=redactor,
            audit=audit,
            approval_timeout_s=policy_cfg.guardrails.approval_timeout_s,
        )
        install_guardrails_routes(app, approvals)
        app[APP_GUARDRAILS_ENABLED] = bool(policy_cfg.guardrails.enabled)
        app[APP_GUARDED_TOOL_RUNNER] = guarded_runner
        app[APP_GUARDRAILS_CTX] = {
            "config": policy_cfg,
            "approvals": approvals,
            "redactor": redactor,
            "audit": audit,
            "policy": policy,
        }
    except Exception as e:
        log.warning("Guardrails unavailable: %s", e)

    # Optional: realtime routes
    try:
        from thomas.realtime.routes import setup_realtime_routes

        setup_realtime_routes(app, require_api_access=lambda req: _require_api_access(req))
    except Exception as e:
        log.warning("Realtime routes unavailable: %s", e)

    # Optional: autonomy engine
    try:
        from thomas.autonomy import install_autonomy

        autonomy_enabled = _env_flag("THOMAS_AUTONOMY_ENABLED", False)
        autonomy_token = os.environ.get("THOMAS_AUTONOMY_TOKEN")
        install_autonomy(app, config, enabled=autonomy_enabled, api_token=autonomy_token)
    except Exception as e:
        log.warning("Autonomy engine unavailable: %s", e)

    # Background engines: ALL engines via unified EngineManager
    # One call starts: persistence, tool_factory, initiative, testing_suite
    try:
        from thomas.core.engine_manager import get_engine_manager

        engine_manager = get_engine_manager()
        results = engine_manager.start_all()
        log.info("EngineManager: started all engines â€” %s", results)

        # Store reference for status endpoint
        app[APP_ENGINE_MANAGER] = engine_manager

    except Exception as e:
        log.warning("Background engines unavailable: %s", e)

    # Optional: swarm cancellation endpoint
    try:
        from thomas.server.swarm_mode import handle_cancel as swarm_cancel_handler

        async def _swarm_cancel_handler(request: web.Request) -> web.Response:
            _require_api_access(request)
            return await swarm_cancel_handler(request)

        app.router.add_post("/api/runs/{run_id}/cancel", _swarm_cancel_handler)
    except Exception as e:
        log.warning("Swarm cancel endpoint unavailable: %s", e)

    _security_headers_enabled = _env_flag("THOMAS_SECURITY_HEADERS_ENABLED", True)
    _frame_options = str(os.environ.get("THOMAS_FRAME_OPTIONS", "SAMEORIGIN") or "").strip()
    _security_headers: Dict[str, str] = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }
    if _frame_options:
        _security_headers["X-Frame-Options"] = _frame_options

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
        # The UI is shipped as unbundled ES modules; browser caching can cause
        # confusing "old code" issues after local edits. Prefer correctness.
        if request.method == "GET" and (
            request.path in {"/", "/mission", "/settings", "/companion"}
            or request.path.startswith("/static/")
        ):
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
        auth = str(request.headers.get("Authorization") or "")
        if auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        return str(request.headers.get("X-Api-Token") or "").strip()

    rate_limit_state: Dict[str, deque[float]] = {}
    rate_limit_lock = asyncio.Lock()
    rate_limit_gc_at = 0.0

    def _parse_server_int(raw: Any, default: int, minimum: int = 1) -> int:
        try:
            val = int(raw)
        except Exception:
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
        cfg: AppConfig = app[APP_CONFIG]
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
            cfg: AppConfig = app[APP_CONFIG]
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

    def _require_api_token(request: web.Request) -> None:
        cfg: AppConfig = app[APP_CONFIG]
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
        cfg: AppConfig = app[APP_CONFIG]
        mode = str(getattr(getattr(cfg, "server", None), "access_mode", "local") or "local").strip().lower()
        if mode == "remote":
            _require_api_token(request)
            return
        _require_loopback(request)

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
        except Exception:
            raise web.HTTPForbidden(text="Invalid Origin header.")

        if origin.scheme not in ("http", "https") or not origin.hostname:
            raise web.HTTPForbidden(text="Invalid Origin header.")

        if not _is_loopback_host(origin.hostname):
            raise web.HTTPForbidden(text="Cross-origin browser requests are not allowed.")

        request_scheme = str(request.url.scheme or "").lower()
        request_host = str(request.url.host or "").lower()
        request_port = int(request.url.port or (443 if request_scheme == "https" else 80))

        origin_scheme = str(origin.scheme or "").lower()
        origin_host = str(origin.hostname or "").lower()
        origin_port = int(origin.port or (443 if origin_scheme == "https" else 80))

        if (
            origin_scheme != request_scheme
            or origin_host != request_host
            or origin_port != request_port
        ):
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
        except Exception as e:
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

    # Optional: webhook routes (FastAPI logic bridged into aiohttp handlers)
    try:
        from thomas.server.routes.webhooks_aiohttp import register_webhooks_routes

        register_webhooks_routes(app, require_api_access=_require_api_access)
    except Exception as e:
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
        cfg: AppConfig = app[APP_CONFIG]
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
        cfg: AppConfig = app[APP_CONFIG]
        base = cfg.get_model(profile)
        secrets: SecretStore = app[APP_SECRETS]
        key = secrets.get(profile)
        if key:
            base = replace(base, api_key=key)
        return base

    def _failover_cfgs_with_secrets(primary_profile: str):
        cfg: AppConfig = app[APP_CONFIG]
        out: List[Any] = []
        for fb in cfg.failover_chain(primary_profile):
            try:
                out.append(_model_cfg_with_secrets(fb.name))
            except Exception as e:
                log.debug("Skipping failover profile %s: %s", getattr(fb, "name", "?"), e)
        return out

    async def _resolve_natural_model_switch_request(
        text: str,
        *,
        current_profile: str,
    ):
        if not is_model_switch_request(text):
            return None

        cfg: AppConfig = app[APP_CONFIG]
        default_models = {
            str(name): str(getattr(model_cfg, "model", "") or "").strip()
            for name, model_cfg in cfg.models.items()
        }
        candidate_profiles = infer_profile_candidates(
            text,
            current_profile=current_profile,
            available_profiles=default_models.keys(),
        )
        discovered: Dict[str, List[str]] = {}
        for profile_name in candidate_profiles[:6]:
            profile_name = str(profile_name or "").strip()
            if not profile_name or profile_name not in cfg.models:
                continue
            ids: List[str] = []
            default_id = default_models.get(profile_name, "")
            if default_id:
                ids.append(default_id)
            try:
                hs = await handshake_models_async(_model_cfg_with_secrets(profile_name), timeout_s=2.5)
                for mid in list(hs.models or []):
                    m = str(mid or "").strip()
                    if m and m not in ids:
                        ids.append(m)
            except Exception as e:
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
        except Exception:
            return int(default)

    def _clone_json(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _chat_file_for(chat_id: str) -> Path:
        digest = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()
        return chat_store_dir / f"{digest}.json"

    def _sanitize_chat_payload(payload: Any, *, chat_id: Optional[str] = None) -> Dict[str, Any]:
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

        messages: List[Dict[str, Any]] = []
        for msg in raw_messages[:2000]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip()
            if role not in ("user", "assistant"):
                continue

            entry: Dict[str, Any] = {
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
                except Exception:
                    entry["content"] = ""

            tool_calls = msg.get("toolCalls")
            if isinstance(tool_calls, list):
                tc_out: List[Dict[str, Any]] = []
                for tc in tool_calls[:200]:
                    if not isinstance(tc, dict):
                        continue
                    try:
                        tc_out.append(_clone_json(tc))
                    except Exception:
                        continue
                entry["toolCalls"] = tc_out
            else:
                entry["toolCalls"] = []

            meta = msg.get("meta")
            if isinstance(meta, dict):
                try:
                    entry["meta"] = _clone_json(meta)
                except Exception:
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

    def _read_chat_from_disk(path: Path) -> Optional[Dict[str, Any]]:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            raw_id = str(payload.get("id") or "").strip()
            if not raw_id:
                return None
            return _sanitize_chat_payload(payload, chat_id=raw_id)
        except Exception as e:
            log.debug("Skipping unreadable chat file %s: %s", path, e)
            return None

    async def _save_chat_to_disk(chat: Dict[str, Any]) -> None:
        payload = json.dumps(chat, ensure_ascii=False, separators=(",", ":"))
        path = _chat_file_for(str(chat.get("id") or ""))
        tmp_path = Path(str(path) + ".tmp")
        async with chat_store_lock:
            chat_store_dir.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(path)

    async def _delete_chat_from_disk(chat_id: str) -> bool:
        path = _chat_file_for(chat_id)
        async with chat_store_lock:
            if not path.exists():
                return False
            path.unlink(missing_ok=True)
        return True

    async def _load_all_chats_from_disk() -> List[Dict[str, Any]]:
        chats: List[Dict[str, Any]] = []
        async with chat_store_lock:
            paths = list(chat_store_dir.glob("*.json"))
        for path in paths:
            chat = _read_chat_from_disk(path)
            if chat is not None:
                chats.append(chat)
        chats.sort(key=lambda c: _safe_int(c.get("updatedAt"), 0), reverse=True)
        return chats

    async def index(request: web.Request) -> web.StreamResponse:
        try:
            html = (web_dir / "index.html").read_text(encoding="utf-8", errors="replace")
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            return web.FileResponse(web_dir / "index.html")

    async def settings(request: web.Request) -> web.StreamResponse:
        try:
            html = (web_dir / "settings.html").read_text(encoding="utf-8", errors="replace")
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            return web.FileResponse(web_dir / "settings.html")

    async def companion(request: web.Request) -> web.StreamResponse:
        try:
            html = (web_dir / "companion.html").read_text(encoding="utf-8", errors="replace")
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            return web.FileResponse(web_dir / "companion.html")

    async def api_models(request: web.Request) -> web.Response:
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        secrets: SecretStore = app[APP_SECRETS]
        profiles = []
        for name, m in cfg.models.items():
            # "has_api_key" is used by the UI as "does this profile need key setup?".
            # Codex uses ChatGPT OAuth via the app-server, so treat it as not requiring an API key.
            has_key = m.provider == "codex" or bool(secrets.get(name) or m.api_key)
            profiles.append(
                {
                    "name": name,
                    "provider": m.provider,
                    "base_url": m.base_url,
                    "model": m.model,
                    "context_window": m.context_window,
                    "max_tokens": m.max_tokens,
                    "has_api_key": has_key,
                }
            )
        return web.json_response(
            {"default": cfg.default_model, "profiles": profiles},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_models_capabilities(request: web.Request) -> web.Response:
        """GET /api/models/capabilities â€” return capability map for all configured profiles."""
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        from thomas.models.capabilities import profile_capability_map
        result: dict = {}
        for name, m in cfg.models.items():
            result[name] = profile_capability_map(m)
        return web.json_response(
            {"profiles": result},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_profile_models(request: web.Request) -> web.Response:
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")
        found = await discover_models_async(_model_cfg_with_secrets(profile), timeout_s=1.5)
        ids = [m.id for m in found]
        # De-dupe while preserving order.
        seen: set[str] = set()
        ids = [x for x in ids if not (x in seen or seen.add(x))]
        return web.json_response({"profile": profile, "models": ids})

    async def api_profile_handshake(request: web.Request) -> web.Response:
        """Probe whether a profile is usable (auth/offline/unsupported), and optionally return model ids.

        Note: restricted by server access policy because it can generate outbound traffic using stored keys.
        """
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")

        result = await handshake_models_async(_model_cfg_with_secrets(profile), timeout_s=2.5)
        payload = {"profile": profile, **result.to_dict()}
        return web.json_response(payload, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_profile_validate(request: web.Request) -> web.Response:
        """Validate profile readiness (handshake + optional tool smoke)."""
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")

        raw_tool_smoke = str(request.query.get("tool_smoke", "1")).strip().lower()
        run_tool_smoke = raw_tool_smoke not in ("0", "false", "no", "off")

        try:
            handshake_timeout_s = float(request.query.get("timeout", "3.0"))
        except Exception:
            handshake_timeout_s = 3.0
        try:
            tool_timeout_s = float(request.query.get("tool_timeout", "20.0"))
        except Exception:
            tool_timeout_s = 20.0

        report = await validate_model_profile_async(
            _model_cfg_with_secrets(profile),
            handshake_timeout_s=max(0.5, min(30.0, handshake_timeout_s)),
            tool_timeout_s=max(2.0, min(120.0, tool_timeout_s)),
            run_tool_smoke=run_tool_smoke,
        )

        # Keep handshake-compatible top-level fields for the web UI, plus tool_smoke details.
        hs = report.handshake
        payload = {
            "profile": profile,
            "provider": report.provider,
            "ok": report.ok,
            "status": hs.status,
            "url": hs.url,
            "http_status": hs.http_status,
            "models": list(hs.models or []),
            "error": hs.error,
            "tool_smoke": report.tool_smoke.to_dict(),
        }
        return web.json_response(payload, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_version(request: web.Request) -> web.Response:
        cfg: AppConfig = app[APP_CONFIG]
        if not bool(getattr(getattr(cfg, "server", None), "allow_unauthenticated_version", True)):
            _require_api_access(request)
        return web.json_response({"version": THOMAS_VERSION})

    async def api_setup_bootstrap(request: web.Request) -> web.Response:
        """Return machine readiness data for first-run onboarding."""
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        secrets_store: SecretStore = app[APP_SECRETS]

        def _first_command(names: List[str]) -> str:
            for name in names:
                found = shutil.which(name)
                if found:
                    return str(found)
            return ""

        codex_cmd = _first_command(["codex", "codex.cmd", "codex.exe"])
        node_cmd = _first_command(["node", "node.exe"])
        npm_cmd = _first_command(["npm", "npm.cmd", "npm.exe"])
        ollama_cmd = _first_command(["ollama", "ollama.exe"])

        local_profile_exists = "local" in cfg.models
        ollama_base = "http://127.0.0.1:11434"
        if local_profile_exists:
            try:
                ollama_base = _ollama_base_url("local")
            except Exception:
                ollama_base = "http://127.0.0.1:11434"
        ollama_check_url = _join_url(ollama_base, "/api/tags")

        ollama_running = False
        ollama_error = ""
        if ollama_cmd:
            try:
                timeout = httpx.Timeout(connect=0.8, read=1.2, write=1.2, pool=1.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(ollama_check_url)
                    if int(resp.status_code) < 500:
                        ollama_running = True
                    else:
                        ollama_error = f"http {int(resp.status_code)}"
            except Exception as e:
                ollama_error = f"{type(e).__name__}: {e}"

        profile_rows: List[Dict[str, Any]] = []
        cloud_key_count = 0
        for name, m in cfg.models.items():
            has_key = m.provider == "codex" or bool(secrets_store.get(name) or m.api_key)
            provider = str(m.provider or "")
            if provider not in {"ollama", "local", "codex"} and has_key:
                cloud_key_count += 1
            profile_rows.append(
                {
                    "name": str(name),
                    "provider": provider,
                    "has_key": bool(has_key),
                }
            )

        if codex_cmd:
            recommended_path = "codex"
            reason = "Codex CLI is installed on this machine."
        elif local_profile_exists and ollama_running:
            recommended_path = "local"
            reason = "Ollama is already running locally."
        elif cloud_key_count > 0:
            recommended_path = "cloud"
            reason = "At least one cloud API key is already configured."
        elif local_profile_exists and ollama_cmd:
            recommended_path = "local"
            reason = "Local profile is available and Ollama is installed."
        else:
            recommended_path = "cloud"
            reason = "Cloud setup is the fastest path when local tools are not installed."

        return web.json_response(
            {
                "system": {
                    "platform": str(sys.platform),
                    "python_version": str(sys.version.split()[0]),
                },
                "tools": {
                    "codex": {
                        "installed": bool(codex_cmd),
                        "command": codex_cmd,
                        "install_hint": "npm i -g @openai/codex",
                        "install_url": "https://developers.openai.com/codex",
                    },
                    "node": {
                        "installed": bool(node_cmd),
                        "command": node_cmd,
                        "install_url": "https://nodejs.org/en/download",
                    },
                    "npm": {
                        "installed": bool(npm_cmd),
                        "command": npm_cmd,
                        "install_url": "https://nodejs.org/en/download",
                    },
                    "ollama": {
                        "installed": bool(ollama_cmd),
                        "running": bool(ollama_running),
                        "command": ollama_cmd,
                        "base_url": ollama_base,
                        "check_url": ollama_check_url,
                        "last_error": ollama_error,
                        "install_url": "https://ollama.com/download",
                    },
                },
                "profiles": {
                    "default": str(cfg.default_model or ""),
                    "rows": profile_rows,
                    "cloud_key_count": int(cloud_key_count),
                },
                "quick_start": {
                    "recommended_path": recommended_path,
                    "reason": reason,
                },
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_setup_repair(request: web.Request) -> web.Response:
        """Run one-click setup repair for local desktop installs."""
        _require_api_access(request)
        _require_loopback(request)
        if request.method.upper() != "POST":
            raise web.HTTPMethodNotAllowed(method=request.method, allowed_methods=["POST"])

        payload: Dict[str, Any] = {}
        if request.can_read_body:
            try:
                payload_raw = await _read_json(request)
                if isinstance(payload_raw, dict):
                    payload = payload_raw
            except web.HTTPUnsupportedMediaType:
                payload = {}
            except web.HTTPBadRequest:
                payload = {}

        def _as_bool(value: Any, default: bool) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
            return default

        auto_install = _as_bool(payload.get("auto_install_tools"), True)
        skip_install = _as_bool(payload.get("skip_install"), False)
        skip_doctor = _as_bool(payload.get("skip_doctor"), False)

        root_dir = Path(__file__).resolve().parents[2]
        repair_script = root_dir / "scripts" / "repair.ps1"
        if not repair_script.exists():
            raise web.HTTPNotFound(text=f"repair script not found: {repair_script}")

        cmd: List[str] = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repair_script),
            "-NoPrompt",
        ]
        if skip_install:
            cmd.append("-SkipInstall")
        if skip_doctor:
            cmd.append("-SkipDoctor")
        if not auto_install:
            cmd.append("-NoAutoInstallTools")

        def _run_repair() -> Dict[str, Any]:
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(root_dir),
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
                stdout = str(completed.stdout or "")
                stderr = str(completed.stderr or "")
                report_path = ""
                for line in stdout.splitlines():
                    if "Repair report:" in line:
                        report_path = line.split("Repair report:", 1)[1].strip()
                return {
                    "ok": int(completed.returncode) == 0,
                    "exit_code": int(completed.returncode),
                    "stdout": stdout,
                    "stderr": stderr,
                    "report_path": report_path,
                }
            except subprocess.TimeoutExpired as e:
                return {
                    "ok": False,
                    "exit_code": 124,
                    "stdout": str((e.stdout or b"").decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")),
                    "stderr": str((e.stderr or b"").decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")),
                    "report_path": "",
                    "error": "repair timed out",
                }
            except Exception as e:
                return {
                    "ok": False,
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "",
                    "report_path": "",
                    "error": f"{type(e).__name__}: {e}",
                }

        result = await asyncio.to_thread(_run_repair)
        stdout_tail = "\n".join(str(result.get("stdout", "")).splitlines()[-40:])
        stderr_tail = "\n".join(str(result.get("stderr", "")).splitlines()[-40:])

        status = 200 if bool(result.get("ok")) else 500
        return web.json_response(
            {
                "ok": bool(result.get("ok")),
                "exit_code": int(result.get("exit_code", 1)),
                "report_path": str(result.get("report_path") or ""),
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
                "error": str(result.get("error") or ""),
                "options": {
                    "auto_install_tools": bool(auto_install),
                    "skip_install": bool(skip_install),
                    "skip_doctor": bool(skip_doctor),
                },
            },
            status=status,
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

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
        tools = [
            {"name": t.name, "category": t.category, "description": t.description}
            for t in registry.list_tools()
        ]
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

    async def api_secrets(request: web.Request) -> web.Response:
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        secrets: SecretStore = app[APP_SECRETS]
        profiles = []
        for name, m in cfg.models.items():
            source = "secret_store" if secrets.get(name) else ("config" if m.api_key else "none")
            profiles.append(
                {
                    "name": name,
                    "provider": m.provider,
                    "base_url": m.base_url,
                    "model": m.model,
                    "has_key": bool(secrets.get(name) or m.api_key),
                    "persisted": secrets.is_persisted(name),
                    "source": source,
                }
            )
        return web.json_response({"storage": secrets.storage_info.__dict__, "profiles": profiles})

    async def api_secret_set(request: web.Request) -> web.Response:
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        secrets: SecretStore = app[APP_SECRETS]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")

        payload = await _read_json(request)
        api_key = str(payload.get("api_key") or "").strip()
        persist = bool(payload.get("persist", True))
        if not api_key:
            raise web.HTTPBadRequest(text="missing api_key")

        secrets.set(profile, api_key, persist=persist)
        return web.json_response({"ok": True, "profile": profile, "persisted": persist})

    async def api_secret_clear(request: web.Request) -> web.Response:
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        secrets: SecretStore = app[APP_SECRETS]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")
        secrets.clear(profile)
        return web.json_response({"ok": True, "profile": profile})

    async def api_local_pull(request: web.Request) -> web.StreamResponse:
        """Pull a local model via Ollama's HTTP API.

        Note: restricted by server access policy and loopback local-model endpoints.
        """
        _require_api_access(request)
        payload = await _read_json(request)
        model_id = str(payload.get("model_id") or payload.get("name") or "").strip()
        if not model_id:
            raise web.HTTPBadRequest(text="missing model_id")

        profile = str(payload.get("profile") or "local").strip() or "local"
        base = _ollama_base_url(profile)
        url = _join_url(base, "/api/pull")

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/x-ndjson; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )
        await resp.prepare(request)

        async def send(obj: Dict[str, Any]) -> None:
            line = json.dumps(obj, ensure_ascii=False)
            await resp.write(line.encode("utf-8") + b"\n")

        ok = True
        try:
            # Keep streaming pulls unbounded for read time, but bound connect/write/pool.
            timeout = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json={"name": model_id}) as r:
                    if r.status_code != 200:
                        text = (await r.aread()).decode("utf-8", errors="replace")
                        await send({"type": "error", "error": f"Ollama {r.status_code}: {text.strip()}"})
                        ok = False
                        await send({"type": "done", "ok": ok})
                        return resp

                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        try:
                            j = json.loads(line)
                            if isinstance(j, dict) and j.get("error"):
                                ok = False
                                await send({"type": "error", "error": str(j.get("error"))})
                            else:
                                await send({"type": "progress", "data": j})
                        except Exception:
                            await send({"type": "progress", "data": {"raw": line}})

            await send({"type": "done", "ok": ok})
        except Exception as e:
            try:
                ok = False
                await send({"type": "error", "error": f"{type(e).__name__}: {e}"})
                await send({"type": "done", "ok": ok})
            except Exception as send_err:
                log.debug("Failed to stream local pull error payload: %s", send_err)
        finally:
            try:
                await resp.write_eof()
            except Exception as eof_err:
                log.debug("Failed to close local pull stream cleanly: %s", eof_err)

        return resp

    async def api_session_new(request: web.Request) -> web.Response:
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        sid = secrets.token_urlsafe(18)
        app[APP_SESSIONS][sid] = ChatSession(
            id=sid, conversation=[], profile=cfg.default_model, model_id=None, autonomy_level=3
        )
        return web.json_response({"session_id": sid})

    async def api_session_fork(request: web.Request) -> web.Response:
        _require_api_access(request)
        payload = await _read_json(request)
        src = str(payload.get("session_id") or "").strip()
        if not src or src not in app[APP_SESSIONS]:
            raise web.HTTPBadRequest(text="missing/invalid session_id")
        base: ChatSession = app[APP_SESSIONS][src]

        sid = secrets.token_urlsafe(18)
        # Deep-copy the conversation to avoid accidental shared mutation.
        cloned = json.loads(json.dumps(base.conversation, ensure_ascii=False))
        app[APP_SESSIONS][sid] = ChatSession(
            id=sid,
            conversation=cloned,
            profile=base.profile,
            model_id=base.model_id,
            autonomy_level=clamp_autonomy_level(getattr(base, "autonomy_level", 3), default=3),
        )
        return web.json_response({"session_id": sid, "forked_from": src})

    async def api_session_import(request: web.Request) -> web.Response:
        _require_api_access(request)
        cfg: AppConfig = app[APP_CONFIG]
        payload = await _read_json(request)

        profile = str(payload.get("profile") or cfg.default_model).strip()
        if profile not in cfg.models:
            raise web.HTTPBadRequest(text=f"unknown profile: {profile}")

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
            # Bound per-message content to avoid huge payloads.
            if len(content) > 120_000:
                content = content[:120_000] + "\n... (truncated)"
            conversation.append({"role": role, "content": content})

        sid = secrets.token_urlsafe(18)
        app[APP_SESSIONS][sid] = ChatSession(
            id=sid,
            conversation=conversation,
            profile=profile,
            model_id=model_id,
            autonomy_level=autonomy_level,
        )
        return web.json_response({"session_id": sid})

    async def api_chat(request: web.Request) -> web.StreamResponse:
        # This endpoint can execute tool-calling flows, including file writes.
        # Keep it access-controlled (local loopback or remote token auth).
        _require_api_access(request)
        start_t = time.monotonic()
        payload = await _read_json(request)
        sid = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not sid:
            # Compatibility mode: allow single-shot callers that do not create
            # a session up front (Claude/OpenAI-style payloads).
            sid = secrets.token_urlsafe(18)

        cfg: AppConfig = app[APP_CONFIG]
        # Sessions are in-memory. If the server restarts, the UI may still have a
        # stale session_id persisted locally; recover by recreating the session.
        if sid not in app[APP_SESSIONS]:
            app[APP_SESSIONS][sid] = ChatSession(
                id=sid, conversation=[], profile=cfg.default_model, model_id=None, autonomy_level=3
            )

        session: ChatSession = app[APP_SESSIONS][sid]

        profile = str(payload.get("profile") or session.profile).strip()
        if profile not in cfg.models:
            raise web.HTTPBadRequest(text=f"unknown profile: {profile}")
        session.profile = profile

        model_id = payload.get("model_id")
        if isinstance(model_id, str) and model_id.strip():
            session.model_id = model_id.strip()
        if "autonomy_level" in payload:
            session.autonomy_level = clamp_autonomy_level(
                payload.get("autonomy_level"),
                default=getattr(session, "autonomy_level", 3),
            )
        if "system_prompt" in payload:
            val = payload.get("system_prompt")
            session.system_prompt = val.strip() if isinstance(val, str) and val.strip() else None

        requested_mode = str(payload.get("mode") or "auto").strip().lower()
        requested_token_economy = str(payload.get("token_economy") or "").strip().lower()
        applied_token_economy, mode, run_cfg, run_max_iterations = apply_token_economy_policy(
            cfg=cfg,
            requested_level=requested_token_economy,
            requested_mode=requested_mode,
        )
        token_economy_meta = build_token_economy_meta(
            requested_level=requested_token_economy,
            applied_level=applied_token_economy,
        )

        text = str(payload.get("text") or payload.get("message") or payload.get("prompt") or "")
        requested_job_type = str(payload.get("job_type") or "").strip().lower() or None
        docs = payload.get("docs") or []
        images = payload.get("images") or []

        run_store_mod = app.get(APP_RUN_STORE_MODULE)
        run_store_enabled = bool(app.get(APP_RUN_STORE_ENABLED)) and run_store_mod is not None

        def _start_run_writer(run_id: str, run_mode: str):
            if not run_store_enabled:
                return None
            try:
                run_store_mod.create_run(
                    {
                        "run_id": run_id,
                        "session_id": sid,
                        "profile": str(session.profile or profile),
                        "model_id": session.model_id,
                        "mode": run_mode,
                        "autonomy_level": int(getattr(session, "autonomy_level", 3) or 3),
                        "thomas_version": THOMAS_VERSION,
                    }
                )
                writer = run_store_mod.ThreadedRunWriter(run_id)
                writer.start()
                return writer
            except Exception as e:
                log.warning("Run store start failed: %s", e)
                return None

        switch_req = await _resolve_natural_model_switch_request(text, current_profile=session.profile)
        control_req = resolve_ui_control_request(text, model_switch=switch_req)
        if control_req is not None:
            return await handle_ui_control_chat(
                request,
                cfg=cfg,
                session=session,
                payload=payload,
                text=text,
                profile=profile,
                mode=mode,
                start_t=start_t,
                token_economy_meta=token_economy_meta,
                switch_req=switch_req,
                control_req=control_req,
                run_store_enabled=run_store_enabled,
                run_store_mod=run_store_mod,
                start_run_writer=_start_run_writer,
                deps=ChatControlDeps(
                    clamp_autonomy_level=clamp_autonomy_level,
                    normalize_usage_payload=_normalize_usage_payload,
                ),
            )

        # Attach docs as plain text blocks.
        if isinstance(docs, list) and docs:
            blocks: List[str] = []
            for d in docs[:6]:
                if not isinstance(d, dict):
                    continue
                name = str(d.get("name") or "document")
                content = str(d.get("text") or "")
                if not content.strip():
                    continue
                # Keep attachments bounded; users can paste more if needed.
                if len(content) > 50_000:
                    content = content[:50_000] + "\n... (truncated)"
                blocks.append(f"--- {name} ---\n{content}\n--- end {name} ---")
            if blocks:
                text = (text.rstrip() + "\n\n[Attached documents]\n" + "\n\n".join(blocks)).strip()

        prompt: Any = text
        if isinstance(images, list) and images:
            img0 = images[0]
            if isinstance(img0, dict) and img0.get("data_url"):
                data_url = str(img0["data_url"])
                prompt = [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]

        # Build per-request model config (allow overriding the model id without mutating global config).
        model_cfg = _model_cfg_with_secrets(profile)
        if session.model_id:
            model_cfg = replace(model_cfg, model=session.model_id)
        fallback_cfgs = _failover_cfgs_with_secrets(profile)

        # Capability fallback: if this profile does not support batch, transparently
        # fall back to normal chat mode instead of erroring.
        if mode == "batch" and not model_supports(model_cfg, "batch"):
            mode = "auto"

        # Batch mode orchestration path.
        if mode == "batch":
            return await handle_batch_mode_chat(
                request,
                session=session,
                text=text,
                start_t=start_t,
                profile=profile,
                cfg=cfg,
                run_cfg=run_cfg,
                model_cfg=model_cfg,
                requested_job_type=requested_job_type,
                token_economy_meta=token_economy_meta,
                run_store_enabled=run_store_enabled,
                run_store_mod=run_store_mod,
                deps=BatchModeDeps(
                    start_run_writer=_start_run_writer,
                    normalize_usage_payload=_normalize_usage_payload,
                    autonomy_level_name=autonomy_level_name,
                    batch_client_factory=OpenAICompatBatchClient,
                    build_completion_request=build_completion_request,
                    parse_batch_state=parse_batch_state,
                    extract_batch_results=extract_batch_results,
                    extract_result_request_id=extract_result_request_id,
                    extract_result_error=extract_result_error,
                    extract_result_text=extract_result_text,
                    evaluate_rules=evaluate_rules,
                    load_config=load_config,
                ),
            )

        # Swarm mode orchestration path.
        if mode == "swarm":
            run_id = secrets.token_urlsafe(10)
            writer = _start_run_writer(run_id, "swarm")
            swarm_next_seq = {"value": 0}

            def _next_seq() -> int:
                try:
                    value = int(swarm_next_seq["value"])
                    if value < 0:
                        value = 0
                except Exception:
                    value = 0
                swarm_next_seq["value"] = value + 1
                return value

            swarm_done: Dict[str, Any] = {
                "ok": None,
                "error": None,
                "iterations": None,
                "tool_calls": None,
                "usage": None,
            }
            try:
                from thomas.server.swarm_mode import handle_swarm_chat

                async def _swarm_tool_call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
                    result = await app[APP_TOOLS].execute(name, args)
                    return {
                        "ok": bool(result.ok),
                        "error": result.error,
                        "data": result.data,
                        "text": result.to_content(),
                    }

                async def _record_swarm_event(evt: Dict[str, Any]) -> None:
                    out = dict(evt or {})
                    out.setdefault("run_id", run_id)
                    if writer is not None:
                        try:
                            out.setdefault("seq", int(writer.seq))
                        except Exception as e:
                            log.debug("Run writer seq assignment failed: %s", e)
                        try:
                            writer.record(out)
                        except Exception as e:
                            log.debug("Run writer record failed (swarm): %s", e)
                    if "seq" not in out:
                        out["seq"] = _next_seq()
                    if str(out.get("type") or "") == "swarm_done":
                        ok_val = bool(out.get("ok", False))
                        swarm_done["ok"] = ok_val
                        swarm_done["error"] = None if ok_val else str(out.get("error") or "swarm failed")
                        summary = out.get("summary")
                        if isinstance(summary, dict):
                            statuses = summary.get("status")
                            if isinstance(statuses, dict):
                                swarm_done["iterations"] = len(statuses)
                        swarm_done["tool_calls"] = None
                        swarm_done["usage"] = _normalize_usage_payload(
                            out.get("run_usage") if "run_usage" in out else out.get("usage")
                        )
                    return out

                subagents = {
                    "planner": _LLMSwarmSubagent(
                        "planner",
                        model_cfg,
                        "You are the planner. Produce strict JSON task graphs only.",
                        fallback_cfgs=fallback_cfgs,
                        failover_enabled=cfg.failover.enabled,
                        failover_cooldown_s=cfg.failover.cooldown_seconds,
                        failover_on_auth_error=cfg.failover.fallback_on_auth_error,
                    ),
                    "coder": _LLMSwarmSubagent(
                        "coder",
                        model_cfg,
                        "You are the coding executor. Produce concrete, implementation-focused output.",
                        fallback_cfgs=fallback_cfgs,
                        failover_enabled=cfg.failover.enabled,
                        failover_cooldown_s=cfg.failover.cooldown_seconds,
                        failover_on_auth_error=cfg.failover.fallback_on_auth_error,
                    ),
                    "tester": _LLMSwarmSubagent(
                        "tester",
                        model_cfg,
                        "You are the validation executor. Focus on tests, checks, and regressions.",
                        fallback_cfgs=fallback_cfgs,
                        failover_enabled=cfg.failover.enabled,
                        failover_cooldown_s=cfg.failover.cooldown_seconds,
                        failover_on_auth_error=cfg.failover.fallback_on_auth_error,
                    ),
                    "reviewer": _LLMSwarmSubagent(
                        "reviewer",
                        model_cfg,
                        "You are the reviewer. Summarize outcomes, risks, and next actions.",
                        fallback_cfgs=fallback_cfgs,
                        failover_enabled=cfg.failover.enabled,
                        failover_cooldown_s=cfg.failover.cooldown_seconds,
                        failover_on_auth_error=cfg.failover.fallback_on_auth_error,
                    ),
                }

                swarm_request = text.strip() if isinstance(text, str) and text.strip() else "No request text provided."
                swarm_payload = dict(payload)
                swarm_payload["token_economy"] = applied_token_economy
                swarm_payload["token_economy_meta"] = dict(token_economy_meta)
                resp = await handle_swarm_chat(
                    request,
                    payload=swarm_payload,
                    user_request=swarm_request,
                    run_id=run_id,
                    session_id=sid,
                    subagents=subagents,
                    tool_call=_swarm_tool_call,
                    tool_mutates_fs=_swarm_tool_mutates_fs,
                    on_event=_record_swarm_event,
                )

                if run_store_enabled:
                    try:
                        ok_val = bool(swarm_done["ok"]) if swarm_done["ok"] is not None else True
                        run_store_mod.finalize_run(
                            run_id,
                            ok=ok_val,
                            error=None if ok_val else str(swarm_done.get("error") or "swarm failed"),
                            iterations=swarm_done.get("iterations"),
                            tool_calls=swarm_done.get("tool_calls"),
                            usage=swarm_done.get("usage"),
                        )
                    except Exception as e:
                        log.warning("Run store finalize failed (swarm): %s", e)
                return resp
            except Exception as e:
                if run_store_enabled:
                    try:
                        run_store_mod.finalize_run(
                            run_id,
                            ok=False,
                            error=f"{type(e).__name__}: {e}",
                            iterations=swarm_done.get("iterations"),
                            tool_calls=swarm_done.get("tool_calls"),
                            usage=swarm_done.get("usage"),
                        )
                    except Exception:
                        log.warning("Run store finalize failed while handling swarm error", exc_info=True)
                raise web.HTTPInternalServerError(text=f"swarm mode unavailable: {type(e).__name__}: {e}")
            finally:
                if writer is not None:
                    try:
                        writer.close()
                    except Exception as e:
                        log.debug("Run writer close failed (swarm): %s", e)

        run_id = secrets.token_urlsafe(10)
        writer = _start_run_writer(run_id, mode)
        run_done: Dict[str, Any] = {
            "ok": None,
            "error": None,
            "iterations": None,
            "tool_calls": None,
            "usage": None,
        }

        chat_auto_failover = bool(getattr(run_cfg.failover, "chat_auto_failover", False))
        failover_enabled_for_chat = bool(run_cfg.failover.enabled and chat_auto_failover)

        llm = LLMClient(
            model_cfg,
            fallback_configs=fallback_cfgs,
            failover_enabled=failover_enabled_for_chat,
            failover_cooldown_s=run_cfg.failover.cooldown_seconds,
            failover_on_auth_error=run_cfg.failover.fallback_on_auth_error,
        )
        tools: ToolRegistry = app[APP_TOOLS]
        memory = app[APP_MEMORY]
        guarded_runner = app[APP_GUARDED_TOOL_RUNNER] if app.get(APP_GUARDRAILS_ENABLED) else None

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/x-ndjson; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )
        await resp.prepare(request)
        send_lock = asyncio.Lock()
        next_seq = {"value": 0}

        def _next_seq() -> int:
            try:
                value = int(next_seq["value"])
                if value < 0:
                    value = 0
            except Exception:
                value = 0
            next_seq["value"] = value + 1
            return value

        async def send(obj: Dict[str, Any]) -> None:
            async with send_lock:
                out = dict(obj)
                out.setdefault("run_id", run_id)
                if writer is not None:
                    try:
                        out.setdefault("seq", int(writer.seq))
                    except Exception as e:
                        log.debug("Run writer seq assignment failed: %s", e)
                    try:
                        writer.record(out)
                    except Exception as e:
                        log.debug("Run writer record failed: %s", e)
                if "seq" not in out:
                    out["seq"] = _next_seq()
                line = json.dumps(out, ensure_ascii=False)
                await resp.write(line.encode("utf-8") + b"\n")

        async def _emit_guardrails_event(evt_type: str, payload_obj: Dict[str, Any]) -> None:
            await send({"type": "guardrails", "event": str(evt_type), "payload": payload_obj})

        requested_runtime = {
            "profile": str(model_cfg.name or profile or ""),
            "provider": str(model_cfg.provider or ""),
            "model": str(model_cfg.model or ""),
            "base_url": str(model_cfg.base_url or ""),
        }

        await send(
            {
                "type": "model_runtime",
                "runtime": {
                    "requested": requested_runtime,
                    "active": requested_runtime,
                    "failover_enabled": bool(failover_enabled_for_chat),
                    "failover_used": False,
                    "attempts": [],
                    "strict_primary_chat": bool(not failover_enabled_for_chat and cfg.failover.enabled),
                },
            }
        )

        agent = AgentLoop(
            run_cfg,
            llm,
            tools,
            system_prompt=session.system_prompt,
            conversation=session.conversation,
            memory=memory,
            thread_id=sid,
            guarded_tool_runner=guarded_runner,
            run_id=run_id,
            session_id=sid,
            guardrails_event_cb=_emit_guardrails_event if guarded_runner is not None else None,
            autonomy_level=int(getattr(session, "autonomy_level", 3) or 3),
        )

        journal: Optional[TaskJournal] = None

        try:
            run_kwargs: Dict[str, Any] = {
                "mode": mode,
                "tools_policy": "auto",
                "job_type": requested_job_type,
                "token_economy": applied_token_economy,
            }
            if run_max_iterations is not None:
                run_kwargs["max_iterations"] = int(run_max_iterations)
            run_kwargs_effective = dict(run_kwargs)
            try:
                run_sig = inspect.signature(agent.run)
                sig_params = tuple(run_sig.parameters.values())
                supports_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig_params)
                if not supports_var_kwargs:
                    allowed = {
                        p.name
                        for p in sig_params
                        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
                    }
                    # `prompt` is the first positional argument passed explicitly.
                    allowed.discard("self")
                    allowed.discard("prompt")
                    dropped = [k for k in list(run_kwargs_effective.keys()) if k not in allowed]
                    for key in dropped:
                        run_kwargs_effective.pop(key, None)
                    if dropped:
                        log.debug(
                            "AgentLoop.run compatibility: dropped unsupported kwargs: %s",
                            ", ".join(sorted(dropped)),
                        )
            except Exception as sig_err:
                log.debug("AgentLoop.run signature inspection failed: %s", sig_err)

            async for event in agent.run(prompt, **run_kwargs_effective):
                if event.type == EventType.AGENT_START:
                    route_data = event.data.get("route", {})
                    await send(
                        {
                            "type": "route",
                            "route": route_data,
                            "mode": event.data.get("mode", "auto"),
                            "token_economy": token_economy_meta,
                            "tools_policy": event.data.get("tools_policy", "auto"),
                            "autonomy_level": int(
                                event.data.get("autonomy_level", getattr(session, "autonomy_level", 3)) or 3
                            ),
                            "autonomy_name": str(
                                event.data.get("autonomy_name")
                                or autonomy_level_name(getattr(session, "autonomy_level", 3))
                            ),
                        }
                    )
                    journal_reason = journal_skip_reason(prompt, route_data, enabled=cfg.journal.enabled)
                    # Task journal: create file if this is a real task
                    if journal_reason is None:
                        try:
                            journal = TaskJournal(
                                journal_dir=cfg.journal.dir_path,
                                run_id=run_id,
                                prompt=prompt,
                                route=route_data,
                                model_info={"model": model_cfg.model, "provider": model_cfg.provider},
                            )
                        except Exception as je:
                            log.debug("Failed to init task journal: %s", je)
                    else:
                        await send({"type": "journal_status", "status": "skipped", "reason": str(journal_reason or "")})
                elif event.type == EventType.TEXT_DELTA:
                    await send({"type": "text", "text": event.data.get("text", "")})
                elif event.type == EventType.AGENT_ITERATION:
                    iter_num = int(event.data.get("iteration", event.iteration))
                    iter_tokens = int(event.data.get("token_estimate", 0))
                    await send(
                        {
                            "type": "iteration",
                            "iteration": iter_num,
                            "token_estimate": iter_tokens,
                            "context_window": int(event.data.get("context_window", 0)),
                        }
                    )
                    if journal is not None:
                        try:
                            journal.log_iteration(iter_num, iter_tokens)
                        except Exception:
                            pass
                elif event.type == EventType.TOOL_CALL_START:
                    await send(
                        {
                            "type": "tool_start",
                            "id": event.data.get("tool_id", ""),
                            "name": event.data.get("tool_name", ""),
                        }
                    )
                elif event.type == EventType.TOOL_CALL_ARGS_DELTA:
                    await send(
                        {
                            "type": "tool_args",
                            "id": event.data.get("tool_id", ""),
                            "delta": event.data.get("delta", ""),
                        }
                    )
                elif event.type == EventType.TOOL_RESULT:
                    tool_ok = bool(event.data.get("ok", False))
                    tool_ms = float(event.data.get("duration_ms", 0.0))
                    tool_name = event.data.get("tool_name", "")
                    await send(
                        {
                            "type": "tool_result",
                            "id": event.data.get("tool_id", ""),
                            "name": tool_name,
                            "ok": tool_ok,
                            "ms": tool_ms,
                            "result": event.data.get("result", ""),
                        }
                    )
                    if journal is not None:
                        try:
                            journal.log_tool_result(tool_name, tool_ok, tool_ms)
                        except Exception:
                            pass
                elif event.type == EventType.AGENT_ERROR:
                    err = str(event.data.get("error", "unknown error"))
                    run_done["ok"] = False
                    run_done["error"] = err
                    await send({"type": "error", "error": err})
                    if journal is not None:
                        try:
                            journal.finalize(ok=False, iterations=0, tool_calls=0, error=err)
                        except Exception:
                            pass
                elif event.type == EventType.AGENT_DONE:
                    usage_obj = _normalize_usage_payload(event.data.get("usage"))
                    session_usage_obj = _normalize_usage_payload(getattr(llm, "session_usage", None))

                    token_report = event.data.get("token_report")
                    if not isinstance(token_report, dict):
                        token_report = {}
                    token_report["token_economy"] = dict(token_economy_meta)
                    compaction_report = None
                    if memory is not None:
                        compact_fn = getattr(memory, "auto_compact_from_token_report", None)
                        if callable(compact_fn):
                            try:
                                compaction_report = await asyncio.to_thread(
                                    compact_fn,
                                    thread_id=sid,
                                    token_report=token_report,
                                )
                            except Exception as compaction_err:
                                log.debug("Token-report memory compaction hook failed: %s", compaction_err)
                    if isinstance(compaction_report, dict):
                        token_report["memory_compaction"] = compaction_report

                    runtime_trace_fn = getattr(llm, "runtime_trace", None)
                    if callable(runtime_trace_fn):
                        try:
                            runtime_model = runtime_trace_fn()
                        except Exception:
                            runtime_model = {
                                "requested": requested_runtime,
                                "active": {
                                    "profile": str(getattr(llm.config, "name", "") or ""),
                                    "provider": str(getattr(llm.config, "provider", "") or ""),
                                    "model": str(getattr(llm.config, "model", "") or ""),
                                    "base_url": str(getattr(llm.config, "base_url", "") or ""),
                                },
                                "failover_enabled": bool(failover_enabled_for_chat),
                                "failover_used": False,
                                "attempts": [],
                            }
                    else:
                        runtime_model = {
                            "requested": requested_runtime,
                            "active": {
                                "profile": str(getattr(llm.config, "name", "") or ""),
                                "provider": str(getattr(llm.config, "provider", "") or ""),
                                "model": str(getattr(llm.config, "model", "") or ""),
                                "base_url": str(getattr(llm.config, "base_url", "") or ""),
                            },
                            "failover_enabled": bool(failover_enabled_for_chat),
                            "failover_used": False,
                            "attempts": [],
                        }
                    if not isinstance(runtime_model, dict):
                        runtime_model = {
                            "requested": requested_runtime,
                            "active": requested_runtime,
                            "failover_enabled": bool(failover_enabled_for_chat),
                            "failover_used": False,
                            "attempts": [],
                        }
                    runtime_model["strict_primary_chat"] = bool(
                        not bool(runtime_model.get("failover_enabled")) and cfg.failover.enabled
                    )

                    done_iterations = int(event.data.get("iterations", 1))
                    done_tool_calls = int(event.data.get("tool_calls", 0))
                    done_total_tokens = int(usage_obj.get("total_tokens", 0) or 0)

                    run_done["ok"] = True
                    run_done["error"] = None
                    run_done["iterations"] = done_iterations
                    run_done["tool_calls"] = done_tool_calls
                    run_done["usage"] = usage_obj

                    if journal is not None:
                        try:
                            journal.finalize(
                                ok=True,
                                iterations=done_iterations,
                                tool_calls=done_tool_calls,
                                total_tokens=done_total_tokens,
                            )
                        except Exception:
                            pass

                    await send({"type": "model_runtime", "runtime": runtime_model})

                    await send(
                        {
                            "type": "done",
                            "iterations": done_iterations,
                            "tool_calls": done_tool_calls,
                            "usage": usage_obj,  # legacy alias for run_usage
                            "run_usage": usage_obj,
                            "session_usage": session_usage_obj,
                            "token_report": token_report,
                            "token_economy": token_economy_meta,
                            "rules_of_road": token_report.get("rules_of_road", {}),
                            "runtime_model": runtime_model,
                            "elapsed_ms": float((time.monotonic() - start_t) * 1000.0),
                        }
                    )
        except Exception as e:
            run_done["ok"] = False
            run_done["error"] = f"{type(e).__name__}: {e}"
            try:
                await send({"type": "error", "error": run_done["error"]})
            except Exception as send_err:
                log.debug("Failed to stream chat error payload: %s", send_err)
        finally:
            # Safety-finalize journal if it wasn't already finalized
            if journal is not None:
                try:
                    journal.finalize(
                        ok=bool(run_done.get("ok")),
                        iterations=int(run_done.get("iterations") or 0),
                        tool_calls=int(run_done.get("tool_calls") or 0),
                        error=run_done.get("error"),
                    )
                except Exception:
                    pass
            await llm.close()
            if run_store_enabled:
                try:
                    ok_val = bool(run_done["ok"]) if run_done["ok"] is not None else False
                    run_store_mod.finalize_run(
                        run_id,
                        ok=ok_val,
                        error=None if ok_val else str(run_done.get("error") or "run failed"),
                        iterations=run_done.get("iterations"),
                        tool_calls=run_done.get("tool_calls"),
                        usage=run_done.get("usage"),
                    )
                except Exception as e:
                    log.warning("Run store finalize failed: %s", e)
            if writer is not None:
                try:
                    writer.close()
                except Exception as e:
                    log.debug("Run writer close failed: %s", e)
            try:
                await resp.write_eof()
            except Exception as eof_err:
                log.debug("Failed to close chat stream cleanly: %s", eof_err)

        return resp

    async def on_cleanup(app_: web.Application) -> None:
        mem = app_.get(APP_MEMORY)
        if mem is not None:
            try:
                mem.close()
            except Exception as e:
                log.debug("Failed to close memory engine during cleanup: %s", e)
    # Codex (ChatGPT OAuth) endpoints

    app.on_cleanup.append(on_cleanup)
    from thomas.server.routes.codex_aiohttp import register_codex_routes
    from thomas.server.routes.companion_aiohttp import register_companion_routes
    from thomas.server.routes.core_aiohttp import register_core_routes
    from thomas.server.routes.gateway import p127_gateway_restart_command as gateway_restart_routes
    from thomas.server.routes.gateway import p134_gateway_usage_cost_command as gateway_usage_cost_routes
    from thomas.server.routes.gateway import p136_gateway_auth_policy_enforcement as gateway_auth_policy_routes
    from thomas.server.routes.gateway import p141_openai_chat_completions_stream as gateway_openai_stream_routes
    from thomas.server.routes.preferences_aiohttp import register_preferences_routes
    from thomas.server.routes.memory_aiohttp import register_memory_routes
    from thomas.server.routes.mission import register_mission_routes

    register_codex_routes(
        app,
        require_api_access=_require_api_access,
        codex_bridge_key=APP_CODEX_BRIDGE,
    )
    register_preferences_routes(app, require_api_access=_require_api_access, read_json=_read_json)
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
        gateway_auth_policy_routes.register(app)
        gateway_usage_cost_routes.register(app)
        gateway_restart_routes.setup_routes(app)
        gateway_openai_stream_routes.register(app)
    except Exception as e:
        log.warning("Gateway control routes unavailable: %s", e)
    register_core_routes(app, web_dir=web_dir, handlers=locals())

    return app


async def serve_async(config: AppConfig, *, host: str = "127.0.0.1", port: int = 8899) -> None:
    from aiohttp import web

    app = create_app(config)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()

    print(f"Thomas UI: http://{host}:{port}/")
    # Keep running until interrupted.
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


def serve(config: AppConfig, *, host: str = "127.0.0.1", port: int = 8899) -> None:
    import asyncio

    asyncio.run(serve_async(config, host=host, port=port))

