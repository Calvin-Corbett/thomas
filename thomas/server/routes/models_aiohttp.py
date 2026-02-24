"""aiohttp route registration for model/profile listing and validation."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from aiohttp import web

from thomas import __version__ as THOMAS_VERSION
from thomas.core.config import AppConfig
from thomas.models.discovery import discover_models_async, handshake_models_async
from thomas.models.protocol import validate_model_profile_async
from thomas.server.app_keys import APP_CONFIG, APP_SECRETS
from thomas.server.secrets import SecretStore

RequireAccessFn = Callable[[web.Request], None]
ModelCfgFn = Callable[[str], Any]


def register_models_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    model_cfg_with_secrets: ModelCfgFn,
) -> None:
    async def api_models(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        secrets: SecretStore = request.app[APP_SECRETS]
        profiles = []
        for name, m in cfg.models.items():
            has_key = m.provider == "codex" or bool(secrets.get(name) or m.api_key)
            profile_info: Dict[str, Any] = {
                    "name": name,
                    "provider": m.provider,
                    "base_url": "codex://app-server" if m.provider == "codex" else m.base_url,
                    "model": m.model,
                    "context_window": m.context_window,
                    "max_tokens": m.max_tokens,
                    "has_api_key": has_key,
                }
            if m.reasoning_effort:
                profile_info["reasoning_effort"] = m.reasoning_effort
            profiles.append(profile_info)
        return web.json_response(
            {"default": cfg.default_model, "profiles": profiles},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_models_capabilities(request: web.Request) -> web.Response:
        """GET /api/models/capabilities - return capability map for all configured profiles."""
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        from thomas.models.capabilities import profile_capability_map
        result: dict = {}
        for name, m in cfg.models.items():
            result[name] = profile_capability_map(m)
        return web.json_response(
            {"profiles": result},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_profile_models(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")
        found = await discover_models_async(model_cfg_with_secrets(profile), timeout_s=1.5)
        ids = [m.id for m in found]
        seen: set[str] = set()
        ids = [x for x in ids if not (x in seen or seen.add(x))]
        return web.json_response({"profile": profile, "models": ids})

    async def api_profile_handshake(request: web.Request) -> web.Response:
        """Probe whether a profile is usable (auth/offline/unsupported), and optionally return model ids."""
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")

        result = await handshake_models_async(model_cfg_with_secrets(profile), timeout_s=2.5)
        payload = {"profile": profile, **result.to_dict()}
        return web.json_response(payload, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_profile_validate(request: web.Request) -> web.Response:
        """Validate profile readiness (handshake + optional tool smoke)."""
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
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
            model_cfg_with_secrets(profile),
            handshake_timeout_s=max(0.5, min(30.0, handshake_timeout_s)),
            tool_timeout_s=max(2.0, min(120.0, tool_timeout_s)),
            run_tool_smoke=run_tool_smoke,
        )

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
        cfg: AppConfig = request.app[APP_CONFIG]
        if not bool(getattr(getattr(cfg, "server", None), "allow_unauthenticated_version", True)):
            require_api_access(request)
        return web.json_response({"version": THOMAS_VERSION})

    app.router.add_get("/api/models", api_models)
    app.router.add_get("/api/models/capabilities", api_models_capabilities)
    app.router.add_get("/api/models/{profile}/ids", api_profile_models)
    app.router.add_get("/api/models/{profile}/handshake", api_profile_handshake)
    app.router.add_get("/api/models/{profile}/validate", api_profile_validate)
    app.router.add_get("/api/version", api_version)
