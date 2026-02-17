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
import ipaddress
import json
import logging
import os
import secrets
import time
from urllib.parse import urlparse
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from thomas import __version__ as THOMAS_VERSION
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig
from thomas.core.events import EventType
from thomas.core.llm import LLMClient
from thomas.models.discovery import discover_models_async, handshake_models_async
from thomas.server.secrets import SecretStore
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.git import register_git_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.shell import register_shell_tools

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


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


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


def create_app(config: AppConfig):
    from aiohttp import web

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

    # Optional: time-travel run store endpoints
    try:
        from thomas.server.routes.runs import register_runs_routes
        from thomas.observability import run_store

        register_runs_routes(app, config)
        app[APP_RUN_STORE_ENABLED] = True
        app[APP_RUN_STORE_MODULE] = run_store
    except Exception as e:
        log.warning("Run store routes unavailable: %s", e)

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

        setup_realtime_routes(app)
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

    # Optional: swarm cancellation endpoint
    try:
        from thomas.server.swarm_mode import handle_cancel as swarm_cancel_handler

        app.router.add_post("/api/runs/{run_id}/cancel", swarm_cancel_handler)
    except Exception as e:
        log.warning("Swarm cancel endpoint unavailable: %s", e)

    @web.middleware
    async def no_cache_ui_assets(request: web.Request, handler):  # type: ignore[no-untyped-def]
        resp = await handler(request)
        # The UI is shipped as unbundled ES modules; browser caching can cause
        # confusing "old code" issues after local edits. Prefer correctness.
        if request.method == "GET" and (request.path == "/" or request.path.startswith("/static/")):
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

    def _require_loopback(request: web.Request) -> None:
        if not _is_loopback_request(request):
            raise web.HTTPForbidden(text="This endpoint is only available from localhost.")
        _require_same_origin_browser_request(request)

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

    async def api_models(request: web.Request) -> web.Response:
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

    async def api_profile_models(request: web.Request) -> web.Response:
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

        Note: restricted to loopback requests because it can generate outbound traffic using stored keys.
        """
        _require_loopback(request)
        cfg: AppConfig = app[APP_CONFIG]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")

        result = await handshake_models_async(_model_cfg_with_secrets(profile), timeout_s=2.5)
        payload = {"profile": profile, **result.to_dict()}
        return web.json_response(payload, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_version(request: web.Request) -> web.Response:
        return web.json_response({"version": THOMAS_VERSION})

    async def api_tools(request: web.Request) -> web.Response:
        registry: ToolRegistry = app[APP_TOOLS]
        tools = [
            {"name": t.name, "category": t.category, "description": t.description}
            for t in registry.list_tools()
        ]
        return web.json_response({"tools": tools})

    async def api_memory(request: web.Request) -> web.Response:
        _require_loopback(request)
        mem = app.get(APP_MEMORY)
        if mem is None:
            return web.json_response({"enabled": False, "error": "memory engine unavailable"})

        sid = str(request.query.get("session_id") or "").strip() or None
        try:
            trace_limit = int(request.query.get("trace_limit", "8"))
        except Exception:
            trace_limit = 8
        trace_limit = max(1, min(50, trace_limit))

        try:
            data = mem.diagnostics(thread=sid, trace_limit=trace_limit)
        except Exception as e:
            return web.json_response({"enabled": False, "error": str(e)}, status=500)

        return web.json_response({
            "enabled": True,
            "thread": sid,
            **data,
        })

    async def api_memory_pin_set(request: web.Request) -> web.Response:
        _require_loopback(request)
        mem = app.get(APP_MEMORY)
        if mem is None:
            return web.json_response({"ok": False, "error": "memory engine unavailable"}, status=503)

        payload = await _read_json(request)
        key = str(payload.get("key") or "").strip()
        text = str(payload.get("text") or "").strip()
        if not key:
            raise web.HTTPBadRequest(text="missing key")
        if not text:
            raise web.HTTPBadRequest(text="missing text")

        mem.pin(key, text)
        return web.json_response({"ok": True, "key": key})

    async def api_memory_pin_clear(request: web.Request) -> web.Response:
        _require_loopback(request)
        mem = app.get(APP_MEMORY)
        if mem is None:
            return web.json_response({"ok": False, "error": "memory engine unavailable"}, status=503)

        key = str(request.match_info.get("key") or "").strip()
        if not key:
            raise web.HTTPBadRequest(text="missing key")
        mem.unpin(key)
        return web.json_response({"ok": True, "key": key})

    async def api_memory_contradictions(request: web.Request) -> web.Response:
        _require_loopback(request)
        mem = app.get(APP_MEMORY)
        if mem is None:
            return web.json_response(
                {"ok": False, "error": "memory engine unavailable"},
                status=503,
            )

        raw_only_open = str(request.query.get("only_open", "1")).strip().lower()
        only_open = raw_only_open not in ("0", "false", "no", "off")
        try:
            limit = int(request.query.get("limit", "50"))
        except Exception:
            limit = 50
        limit = max(1, min(500, limit))

        list_fn = getattr(mem, "list_contradictions", None)
        if not callable(list_fn):
            return web.json_response(
                {
                    "ok": False,
                    "error": "contradiction API unavailable for current memory backend",
                },
                status=501,
            )

        try:
            rows = list_fn(only_open=only_open, limit=limit)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

        return web.json_response(
            {
                "ok": True,
                "only_open": only_open,
                "count": len(rows) if isinstance(rows, list) else 0,
                "contradictions": rows if isinstance(rows, list) else [],
            }
        )

    async def api_memory_contradiction_resolve(request: web.Request) -> web.Response:
        _require_loopback(request)
        mem = app.get(APP_MEMORY)
        if mem is None:
            return web.json_response(
                {"ok": False, "error": "memory engine unavailable"},
                status=503,
            )

        cid_raw = str(request.match_info.get("cid") or "").strip()
        if not cid_raw:
            raise web.HTTPBadRequest(text="missing contradiction id")
        try:
            cid = int(cid_raw)
        except Exception:
            raise web.HTTPBadRequest(text="invalid contradiction id")
        if cid <= 0:
            raise web.HTTPBadRequest(text="invalid contradiction id")

        resolved = True
        try:
            payload = await _read_json(request)
        except web.HTTPBadRequest:
            payload = {}
        if isinstance(payload, dict) and "resolved" in payload:
            resolved = bool(payload.get("resolved"))

        resolve_fn = getattr(mem, "resolve_contradiction", None)
        if not callable(resolve_fn):
            return web.json_response(
                {
                    "ok": False,
                    "error": "contradiction API unavailable for current memory backend",
                },
                status=501,
            )

        try:
            ok = bool(resolve_fn(cid, resolved=resolved))
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        if not ok:
            return web.json_response(
                {"ok": False, "error": "failed to update contradiction"},
                status=500,
            )
        return web.json_response({"ok": True, "id": cid, "resolved": bool(resolved)})

    async def api_secrets(request: web.Request) -> web.Response:
        _require_loopback(request)
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
        _require_loopback(request)
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
        _require_loopback(request)
        cfg: AppConfig = app[APP_CONFIG]
        secrets: SecretStore = app[APP_SECRETS]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")
        secrets.clear(profile)
        return web.json_response({"ok": True, "profile": profile})

    async def api_local_pull(request: web.Request) -> web.StreamResponse:
        """Pull a local model via Ollama's HTTP API.

        Note: restricted to loopback requests and loopback endpoints.
        """
        _require_loopback(request)
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
        _require_loopback(request)
        cfg: AppConfig = app[APP_CONFIG]
        sid = secrets.token_urlsafe(18)
        app[APP_SESSIONS][sid] = ChatSession(
            id=sid, conversation=[], profile=cfg.default_model, model_id=None
        )
        return web.json_response({"session_id": sid})

    async def api_session_fork(request: web.Request) -> web.Response:
        _require_loopback(request)
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
        )
        return web.json_response({"session_id": sid, "forked_from": src})

    async def api_session_import(request: web.Request) -> web.Response:
        _require_loopback(request)
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
            id=sid, conversation=conversation, profile=profile, model_id=model_id
        )
        return web.json_response({"session_id": sid})

    async def api_chat(request: web.Request) -> web.StreamResponse:
        # This endpoint can execute tool-calling flows, including file writes.
        # Keep it localhost-only for safe-by-default behavior.
        _require_loopback(request)
        start_t = time.monotonic()
        payload = await _read_json(request)
        sid = str(payload.get("session_id", "")).strip()
        if not sid:
            raise web.HTTPBadRequest(text="missing/invalid session_id")

        cfg: AppConfig = app[APP_CONFIG]
        # Sessions are in-memory. If the server restarts, the UI may still have a
        # stale session_id persisted locally; recover by recreating the session.
        if sid not in app[APP_SESSIONS]:
            app[APP_SESSIONS][sid] = ChatSession(
                id=sid, conversation=[], profile=cfg.default_model, model_id=None
            )

        session: ChatSession = app[APP_SESSIONS][sid]

        profile = str(payload.get("profile") or session.profile).strip()
        if profile not in cfg.models:
            raise web.HTTPBadRequest(text=f"unknown profile: {profile}")
        session.profile = profile

        model_id = payload.get("model_id")
        if isinstance(model_id, str) and model_id.strip():
            session.model_id = model_id.strip()

        mode = str(payload.get("mode") or "auto").strip().lower()
        if mode not in ("auto", "fast", "thinking", "swarm"):
            mode = "auto"

        text = str(payload.get("text") or "")
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
                        "profile": profile,
                        "model_id": session.model_id,
                        "mode": run_mode,
                        "thomas_version": THOMAS_VERSION,
                    }
                )
                writer = run_store_mod.ThreadedRunWriter(run_id)
                writer.start()
                return writer
            except Exception as e:
                log.warning("Run store start failed: %s", e)
                return None

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

        # Swarm mode orchestration path.
        if mode == "swarm":
            run_id = secrets.token_urlsafe(10)
            writer = _start_run_writer(run_id, "swarm")
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
                            writer.record(out)
                        except Exception as e:
                            log.debug("Run writer record failed (swarm): %s", e)
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
                        swarm_done["usage"] = None

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
                resp = await handle_swarm_chat(
                    request,
                    payload=payload,
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

        llm = LLMClient(
            model_cfg,
            fallback_configs=fallback_cfgs,
            failover_enabled=cfg.failover.enabled,
            failover_cooldown_s=cfg.failover.cooldown_seconds,
            failover_on_auth_error=cfg.failover.fallback_on_auth_error,
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

        async def send(obj: Dict[str, Any]) -> None:
            async with send_lock:
                out = dict(obj)
                out.setdefault("run_id", run_id)
                if writer is not None:
                    try:
                        writer.record(out)
                    except Exception as e:
                        log.debug("Run writer record failed: %s", e)
                line = json.dumps(out, ensure_ascii=False)
                await resp.write(line.encode("utf-8") + b"\n")

        async def _emit_guardrails_event(evt_type: str, payload_obj: Dict[str, Any]) -> None:
            await send({"type": "guardrails", "event": str(evt_type), "payload": payload_obj})

        agent = AgentLoop(
            cfg,
            llm,
            tools,
            conversation=session.conversation,
            memory=memory,
            thread_id=sid,
            guarded_tool_runner=guarded_runner,
            run_id=run_id,
            session_id=sid,
            guardrails_event_cb=_emit_guardrails_event if guarded_runner is not None else None,
        )

        try:
            async for event in agent.run(prompt, mode=mode, tools_policy="auto"):
                if event.type == EventType.AGENT_START:
                    await send(
                        {
                            "type": "route",
                            "route": event.data.get("route", {}),
                            "mode": event.data.get("mode", "auto"),
                            "tools_policy": event.data.get("tools_policy", "auto"),
                        }
                    )
                elif event.type == EventType.TEXT_DELTA:
                    await send({"type": "text", "text": event.data.get("text", "")})
                elif event.type == EventType.AGENT_ITERATION:
                    await send(
                        {
                            "type": "iteration",
                            "iteration": int(event.data.get("iteration", event.iteration)),
                            "token_estimate": int(event.data.get("token_estimate", 0)),
                            "context_window": int(event.data.get("context_window", 0)),
                        }
                    )
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
                    await send(
                        {
                            "type": "tool_result",
                            "id": event.data.get("tool_id", ""),
                            "name": event.data.get("tool_name", ""),
                            "ok": bool(event.data.get("ok", False)),
                            "ms": float(event.data.get("duration_ms", 0.0)),
                            "result": event.data.get("result", ""),
                        }
                    )
                elif event.type == EventType.AGENT_ERROR:
                    err = str(event.data.get("error", "unknown error"))
                    run_done["ok"] = False
                    run_done["error"] = err
                    await send({"type": "error", "error": err})
                elif event.type == EventType.AGENT_DONE:
                    usage_obj: Dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                    usage = event.data.get("usage")
                    if isinstance(usage, dict):
                        usage_obj = {
                            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                            "total_tokens": int(usage.get("total_tokens", 0) or 0),
                        }
                    else:
                        usage = getattr(llm, "session_usage", None)
                        if usage is not None:
                            usage_obj = {
                                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                            }

                    token_report = event.data.get("token_report")
                    if not isinstance(token_report, dict):
                        token_report = {}

                    run_done["ok"] = True
                    run_done["error"] = None
                    run_done["iterations"] = int(event.data.get("iterations", 1))
                    run_done["tool_calls"] = int(event.data.get("tool_calls", 0))
                    run_done["usage"] = usage_obj

                    await send(
                        {
                            "type": "done",
                            "iterations": int(event.data.get("iterations", 1)),
                            "tool_calls": int(event.data.get("tool_calls", 0)),
                            "usage": usage_obj,
                            "token_report": token_report,
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

    # ── Codex (ChatGPT OAuth) endpoints ─────────────────────

    async def api_codex_status(request: web.Request) -> web.Response:
        _require_loopback(request)
        try:
            from thomas.codex.bridge import CodexBridge
            bridge: CodexBridge = app.get(APP_CODEX_BRIDGE)  # type: ignore
            if bridge is None:
                bridge = CodexBridge()
                await bridge.start()
                app[APP_CODEX_BRIDGE] = bridge
            acct = await bridge.check_auth()
            return web.json_response({
                "logged_in": acct.logged_in,
                "email": acct.email,
                "plan_type": acct.plan_type,
                "auth_type": acct.auth_type,
            })
        except Exception as e:
            return web.json_response({"logged_in": False, "error": str(e)})

    async def api_codex_login(request: web.Request) -> web.Response:
        _require_loopback(request)
        try:
            from thomas.codex.bridge import CodexBridge
            bridge: CodexBridge = app.get(APP_CODEX_BRIDGE)  # type: ignore
            if bridge is None:
                bridge = CodexBridge()
                await bridge.start()
                app[APP_CODEX_BRIDGE] = bridge
            acct = await bridge.check_auth()
            if acct.logged_in:
                return web.json_response({
                    "ok": True, "already": True,
                    "email": acct.email, "plan_type": acct.plan_type,
                })
            acct = await bridge.login_chatgpt()
            return web.json_response({
                "ok": True, "already": False,
                "email": acct.email, "plan_type": acct.plan_type,
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def api_codex_logout(request: web.Request) -> web.Response:
        _require_loopback(request)
        try:
            bridge = app.get(APP_CODEX_BRIDGE)
            if bridge is not None:
                await bridge.logout()
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def api_codex_models(request: web.Request) -> web.Response:
        _require_loopback(request)
        try:
            from thomas.codex.bridge import CodexBridge
            bridge: CodexBridge = app.get(APP_CODEX_BRIDGE)  # type: ignore
            if bridge is None:
                bridge = CodexBridge()
                await bridge.start()
                app[APP_CODEX_BRIDGE] = bridge
            models_found = await bridge.list_models()
            return web.json_response({
                "models": [{"id": m.id, "display_name": m.display_name, "is_default": m.is_default} for m in models_found]
            })
        except Exception as e:
            return web.json_response({"models": [], "error": str(e)})

    app.on_cleanup.append(on_cleanup)

    # Codex bridge cleanup
    async def on_codex_cleanup(app_: web.Application) -> None:
        bridge = app_.get(APP_CODEX_BRIDGE)
        if bridge is not None:
            try:
                await bridge.stop()
            except Exception as e:
                log.debug("Failed to stop Codex bridge during cleanup: %s", e)

    app.on_cleanup.append(on_codex_cleanup)

    # Routes
    app.router.add_get("/", index)
    # Serve nested static assets (e.g. /static/css/layout.css, /static/js/app.js)
    app.router.add_static("/static/", web_dir, show_index=False)
    app.router.add_get("/api/models", api_models)
    app.router.add_get("/api/models/{profile}/ids", api_profile_models)
    app.router.add_get("/api/models/{profile}/handshake", api_profile_handshake)
    app.router.add_get("/api/version", api_version)
    app.router.add_get("/api/tools", api_tools)
    app.router.add_get("/api/memory", api_memory)
    app.router.add_post("/api/memory/pins", api_memory_pin_set)
    app.router.add_delete("/api/memory/pins/{key}", api_memory_pin_clear)
    app.router.add_get("/api/memory/contradictions", api_memory_contradictions)
    app.router.add_post("/api/memory/contradictions/{cid}/resolve", api_memory_contradiction_resolve)
    app.router.add_get("/api/secrets", api_secrets)
    app.router.add_post("/api/secrets/{profile}", api_secret_set)
    app.router.add_delete("/api/secrets/{profile}", api_secret_clear)
    app.router.add_post("/api/local/pull", api_local_pull)
    app.router.add_post("/api/session/new", api_session_new)
    app.router.add_post("/api/session/fork", api_session_fork)
    app.router.add_post("/api/session/import", api_session_import)
    app.router.add_post("/api/chat", api_chat)
    app.router.add_get("/api/codex/status", api_codex_status)
    app.router.add_post("/api/codex/login", api_codex_login)
    app.router.add_post("/api/codex/logout", api_codex_logout)
    app.router.add_get("/api/codex/models", api_codex_models)

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
