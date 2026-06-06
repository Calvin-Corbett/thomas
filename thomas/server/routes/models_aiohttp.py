"""aiohttp route registration for model/profile listing and validation."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas import __version__ as THOMAS_VERSION
from thomas.core.config import AppConfig, load_config
from thomas.models.discovery import discover_models_async, handshake_models_async
from thomas.models.protocol import validate_model_profile_async
from thomas.server.app_keys import APP_CONFIG, APP_RUNTIME_GUARD_STATE, APP_SECRETS
from thomas.server.secrets import SecretStore

RequireAccessFn = Callable[[web.Request], None]
ModelCfgFn = Callable[[str], Any]

_RUNTIME_MODE_PROD_ENV = frozenset({"prod", "production", "release", "live"})
_RUNTIME_MODE_PROD_BRANCH = frozenset({"prod", "production", "release", "stable"})


def _appkey_identity(key: Any) -> str:
    rep = repr(key)
    match = re.match(r"^<AppKey\(([^,]+),\s*type=.*\)>$", rep)
    if match:
        name = str(match.group(1) or "")
        marker = "thomas.server.app_keys."
        idx = name.find(marker)
        if idx >= 0:
            return name[idx:]
        return name
    return str(key)


def _resolve_app_value(
    app: web.Application,
    key: Any,
    *,
    expected_type: Any = None,
    default: Any = None,
    required: bool = False,
) -> Any:
    value = app.get(key)
    if expected_type is None:
        if value is not None:
            return value
    elif isinstance(value, expected_type):
        return value

    target_identity = _appkey_identity(key)
    for existing_key, existing_value in app.items():
        if _appkey_identity(existing_key) != target_identity:
            continue
        if expected_type is not None and not isinstance(existing_value, expected_type):
            continue
        app[key] = existing_value
        return existing_value

    if required:
        raise KeyError(key)
    return default


def _resolve_runtime_config(app: web.Application) -> AppConfig:
    cfg = _resolve_app_value(app, APP_CONFIG, expected_type=AppConfig)
    if isinstance(cfg, AppConfig):
        return cfg
    for value in app.values():
        if isinstance(value, AppConfig):
            app[APP_CONFIG] = value
            return value
    cfg = load_config()
    app[APP_CONFIG] = cfg
    return cfg


def _runtime_guard_payload(app: web.Application) -> dict[str, Any]:
    state = _resolve_app_value(app, APP_RUNTIME_GUARD_STATE, expected_type=dict, default={})
    if not isinstance(state, dict) or not state:
        return {
            "enabled": False,
            "is_latest_code": True,
            "state": "unknown",
            "checked_at_utc": "",
            "reasons": [],
            "alert_message": "",
            "git_branch": "",
            "pid": None,
            "lock_pid": None,
            "lock_port": None,
        }

    status = state.get("status") if isinstance(state.get("status"), dict) else {}
    current = state.get("current") if isinstance(state.get("current"), dict) else {}
    current_source = current.get("source") if isinstance(current.get("source"), dict) else {}
    boot = state.get("boot") if isinstance(state.get("boot"), dict) else {}
    boot_source = boot.get("source") if isinstance(boot.get("source"), dict) else {}
    lock = current.get("lock") if isinstance(current.get("lock"), dict) else {}
    return {
        "enabled": bool(state.get("enabled", True)),
        "is_latest_code": bool(status.get("is_latest_code", True)),
        "state": str(status.get("state") or "unknown"),
        "checked_at_utc": str(status.get("checked_at_utc") or ""),
        "reasons": list(status.get("reasons") or []),
        "alert_message": str(status.get("alert_message") or ""),
        "git_branch": str(current_source.get("git_branch") or boot_source.get("git_branch") or ""),
        "pid": current.get("pid"),
        "lock_pid": lock.get("pid"),
        "lock_port": lock.get("port"),
    }


def _runtime_mode_payload(app: web.Application) -> dict[str, str]:
    runtime_guard = _runtime_guard_payload(app)
    git_branch = str(runtime_guard.get("git_branch") or "").strip()
    env_raw = str(os.environ.get("THOMAS_ENV") or os.environ.get("PYTHON_ENV") or os.environ.get("ENV") or "").strip()
    env_norm = env_raw.lower()
    branch_norm = git_branch.lower()

    label = "DEV"
    source = "default"
    if env_norm in _RUNTIME_MODE_PROD_ENV:
        label = "PROD"
        source = "env"
    elif branch_norm in _RUNTIME_MODE_PROD_BRANCH:
        label = "PROD"
        source = "git_branch"
    elif env_norm:
        source = "env"
    elif branch_norm:
        source = "git_branch"

    return {
        "label": label,
        "source": source,
        "env": env_raw,
        "git_branch": git_branch,
    }


def _resolve_default_model(cfg: AppConfig) -> tuple[str, str]:
    try:
        from thomas.core.model_resolution import resolve_effective_model
        from thomas.preferences.store import get_db_path

        resolved_profile, resolved_model_id = resolve_effective_model(
            cfg,
            env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
            user_id="default",
            db_path=get_db_path(),
        )
        if resolved_profile in cfg.models:
            return resolved_profile, str(resolved_model_id or "")
    except Exception:
        pass
    fallback = str(cfg.default_model or "").strip()
    if fallback not in cfg.models and cfg.models:
        fallback = next(iter(cfg.models))
    return fallback, ""


def _model_preferences_payload() -> dict[str, Any]:
    try:
        from thomas.preferences.store import PreferencesStore, get_db_path

        prefs = PreferencesStore(get_db_path()).get(user_id="default")
        model_prefs = getattr(getattr(prefs, "advanced", None), "model", None)
        return {
            "active_profile": str(getattr(model_prefs, "active_profile", "") or "").strip(),
            "model_id": str(getattr(model_prefs, "model_id", "") or "").strip(),
            "role_profiles": dict(getattr(model_prefs, "role_profiles", {}) or {}),
            "role_model_ids": dict(getattr(model_prefs, "role_model_ids", {}) or {}),
        }
    except Exception:
        return {
            "active_profile": "",
            "model_id": "",
            "role_profiles": {},
            "role_model_ids": {},
        }


def register_models_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    model_cfg_with_secrets: ModelCfgFn,
) -> None:
    async def api_models(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = _resolve_runtime_config(request.app)
        resolved_default, _resolved_default_model_id = _resolve_default_model(cfg)
        secrets: SecretStore = _resolve_app_value(request.app, APP_SECRETS, required=True)
        from thomas.models.chat_capabilities import profile_chat_control_map

        profiles = []
        for name, m in cfg.models.items():
            provider_name = str(m.provider or "").strip().lower().replace("-", "_")
            if provider_name == "openai_codex":
                try:
                    from thomas.server.openai_codex_oauth import has_openai_codex_token

                    has_key = bool(m.api_key or has_openai_codex_token(secrets, name))
                except Exception:
                    has_key = bool(m.api_key)
            else:
                has_key = provider_name == "codex" or bool(secrets.get(name) or m.api_key)
            profile_info: dict[str, Any] = {
                "name": name,
                "provider": m.provider,
                "base_url": (
                    "codex://app-server"
                    if provider_name == "codex"
                    else ("https://chatgpt.com/backend-api/codex" if provider_name == "openai_codex" else m.base_url)
                ),
                "model": m.model,
                "context_window": m.context_window,
                "max_tokens": m.max_tokens,
                "has_api_key": has_key,
                "chat_controls": profile_chat_control_map(m),
            }
            if m.reasoning_effort:
                profile_info["reasoning_effort"] = m.reasoning_effort
            profiles.append(profile_info)
        payload: dict[str, Any] = {
            "default": resolved_default or cfg.default_model,
            "profiles": profiles,
            "preferences": _model_preferences_payload(),
        }
        if str(request.query.get("catalog", "")).strip().lower() in {"1", "true", "yes"}:
            from thomas.models.catalog import get_model_catalog_async

            refresh_raw = str(request.query.get("refresh", "")).strip().lower()
            cached_raw = str(request.query.get("cached", "")).strip().lower()
            if refresh_raw in {"1", "true", "yes"}:
                catalog_refresh: bool | None = True
            elif cached_raw in {"1", "true", "yes"}:
                catalog_refresh = False
            else:
                catalog_refresh = None
            payload["catalog"] = await get_model_catalog_async(cfg, refresh=catalog_refresh, timeout_s=1.5)
        return web.json_response(
            payload,
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_models_capabilities(request: web.Request) -> web.Response:
        """GET /api/models/capabilities - return capability map for all configured profiles."""
        require_api_access(request)
        cfg: AppConfig = _resolve_runtime_config(request.app)
        from thomas.models.capabilities import profile_capability_map
        from thomas.models.chat_capabilities import profile_chat_control_map

        result: dict[str, Any] = {}
        chat_controls: dict[str, Any] = {}
        for name, m in cfg.models.items():
            result[name] = profile_capability_map(m)
            chat_controls[name] = profile_chat_control_map(m)
        return web.json_response(
            {"profiles": result, "chat_controls": {"profiles": chat_controls}},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_profile_models(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = _resolve_runtime_config(request.app)
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
        cfg: AppConfig = _resolve_runtime_config(request.app)
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")

        result = await handshake_models_async(model_cfg_with_secrets(profile), timeout_s=2.5)
        payload = {"profile": profile, **result.to_dict()}
        return web.json_response(payload, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_profile_validate(request: web.Request) -> web.Response:
        """Validate profile readiness (handshake + optional tool smoke)."""
        require_api_access(request)
        cfg: AppConfig = _resolve_runtime_config(request.app)
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

    async def api_models_catalog(request: web.Request) -> web.Response:
        """GET /api/models/catalog - return cached or refreshed model catalog."""
        require_api_access(request)
        cfg: AppConfig = _resolve_runtime_config(request.app)
        from thomas.models.catalog import get_model_catalog_async

        refresh_raw = str(request.query.get("refresh", "")).strip().lower()
        cached_raw = str(request.query.get("cached", "")).strip().lower()
        if refresh_raw in {"1", "true", "yes"}:
            refresh: bool | None = True
        elif cached_raw in {"1", "true", "yes"}:
            refresh = False
        else:
            refresh = None
        payload = await get_model_catalog_async(cfg, refresh=refresh, timeout_s=1.5)
        return web.json_response(payload, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_version(request: web.Request) -> web.Response:
        cfg: AppConfig = _resolve_runtime_config(request.app)
        if not bool(getattr(getattr(cfg, "server", None), "allow_unauthenticated_version", True)):
            require_api_access(request)
        return web.json_response(
            {
                "version": THOMAS_VERSION,
                "runtime_guard": _runtime_guard_payload(request.app),
                "runtime_mode": _runtime_mode_payload(request.app),
            }
        )

    app.router.add_get("/api/models", api_models)
    app.router.add_get("/api/models/catalog", api_models_catalog)
    app.router.add_get("/api/models/capabilities", api_models_capabilities)
    app.router.add_get("/api/models/{profile}/ids", api_profile_models)
    app.router.add_get("/api/models/{profile}/handshake", api_profile_handshake)
    app.router.add_get("/api/models/{profile}/validate", api_profile_validate)
    app.router.add_get("/api/version", api_version)
