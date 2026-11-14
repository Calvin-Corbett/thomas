"""aiohttp route registration for model/profile listing and validation."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.core.config import AppConfig, load_config
from thomas.models.discovery import discover_models_async, handshake_models_async
from thomas.models.protocol import validate_model_profile_async
from thomas.server.app_keys import APP_CONFIG, APP_MODEL_CATALOG, APP_SECRETS
from thomas.server.secrets import SecretStore

log = logging.getLogger(__name__)

RequireAccessFn = Callable[[web.Request], None]
ModelCfgFn = Callable[[str], Any]


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


def _resolve_default_model(cfg: AppConfig) -> tuple[str, str]:
    try:
        from thomas.preferences.model_resolution import resolve_effective_model
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
    # The preferences store is sqlite behind an optional import: ImportError if the
    # module is absent, OSError/sqlite3.Error for the file and the query, and
    # TypeError/ValueError/AttributeError for a row that is not shaped like the
    # model prefs. Defaults are a legitimate answer, but say why they were used.
    except (ImportError, OSError, sqlite3.Error, TypeError, ValueError, AttributeError):
        log.warning("Model preferences unavailable; reporting defaults", exc_info=True)
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
    from thomas.models.catalog import catalog_view
    from thomas.models.catalog_refresh import CatalogRefresher, autorefresh_enabled

    async def _codex_token(profile: str) -> str:
        from thomas.server.openai_codex_oauth import ensure_openai_codex_access_token

        store = _resolve_app_value(app, APP_SECRETS, required=False)
        return await ensure_openai_codex_access_token(profile, secret_store=store)

    refresher = CatalogRefresher(
        lambda: _resolve_runtime_config(app), cfg_with_secrets=model_cfg_with_secrets, codex_token=_codex_token
    )
    app[APP_MODEL_CATALOG] = refresher

    def _runtime_api_key(profile: str, declared: Any) -> str:
        """The API key the chat turn for *profile* will actually run with.

        ``model_cfg_with_secrets`` is the one resolver the chat stream uses
        (``chat_aiohttp_streaming.py``) and the catalog refresher above, so asking
        it here is the only way this route can answer who serves a profile in the
        same terms as the engine that serves it. Reading the secret store directly
        instead answered for a key the turn may never receive.
        """
        try:
            resolved = model_cfg_with_secrets(profile)
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            log.debug("could not resolve the runtime config for profile %s", profile, exc_info=True)
            resolved = None
        return str(getattr(declared if resolved is None else resolved, "api_key", "") or "")

    async def _start_catalog(_app: web.Application) -> None:
        if autorefresh_enabled():
            refresher.start()

    async def _stop_catalog(_app: web.Application) -> None:
        await refresher.stop()

    if not app.on_startup.frozen:
        app.on_startup.append(_start_catalog)
        app.on_cleanup.append(_stop_catalog)

    async def api_models(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = _resolve_runtime_config(request.app)
        resolved_default, _resolved_default_model_id = _resolve_default_model(cfg)
        secrets: SecretStore = _resolve_app_value(request.app, APP_SECRETS, required=True)
        from thomas.core.claude_plan import claude_plan_ready
        from thomas.models.chat_capabilities import profile_chat_control_map
        from thomas.models.sources import is_local_profile

        profiles = []
        for name, m in cfg.models.items():
            provider_name = str(m.provider or "").strip().lower().replace("-", "_")
            if provider_name == "openai_codex":
                try:
                    from thomas.server.openai_codex_oauth import has_openai_codex_token

                    has_key = bool(m.api_key or has_openai_codex_token(secrets, name))
                # Reading a stored OAuth token: ImportError if the OAuth module is
                # absent, OSError for the secret file, ValueError/TypeError/KeyError
                # for a token blob that will not parse. Fall back to the plain key.
                except (ImportError, OSError, ValueError, TypeError, KeyError):
                    log.debug("openai_codex token probe failed for profile %s", name, exc_info=True)
                    has_key = bool(m.api_key)
            else:
                has_key = bool(secrets.get(name) or m.api_key)
            profile_info: dict[str, Any] = {
                "name": name,
                "provider": m.provider,
                "base_url": (
                    "https://chatgpt.com/backend-api/codex" if provider_name == "openai_codex" else m.base_url
                ),
                "model": m.model,
                "context_window": m.context_window,
                "max_tokens": m.max_tokens,
                "has_api_key": has_key,
                "keyless_ok": is_local_profile(provider_name, m),
                # Your Claude plan serves this profile through the Claude CLI's own
                # sign-in, so no key is needed and the picker may offer it. False
                # once the turn would run with a key (Anthropic's API answers then)
                # and false when the CLI is not installed, so nothing is offered
                # that cannot run. Read from the runtime's own key rather than from
                # the secret store, so this flag and the transport that honours it
                # (llm_transport_pool.py) cannot label one profile two ways.
                "claude_plan": claude_plan_ready(provider_name, _runtime_api_key(name, m)),
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
            # GET never refreshes (a GET isn't covered by the mutating-route origin
            # check): only POST /api/models/catalog/refresh asks the providers.
            payload["catalog"] = catalog_view(await refresher.current())
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
        except (TypeError, ValueError):  # a query string that is not a number -> use the default
            handshake_timeout_s = 3.0
        try:
            tool_timeout_s = float(request.query.get("tool_timeout", "20.0"))
        except (TypeError, ValueError):
            tool_timeout_s = 20.0

        profile_cfg = model_cfg_with_secrets(profile)

        # Self-heal the most common local failure before declaring it: an
        # installed-but-not-running Ollama. The setup wizard's "Connect and
        # Test" lands here — start the backend so the test can pass instead
        # of telling the user to go start it themselves.
        from thomas.core.ollama_autostart import maybe_autostart_ollama

        if maybe_autostart_ollama(getattr(profile_cfg, "base_url", None)):
            import asyncio as _asyncio

            await _asyncio.sleep(2.5)  # give the backend a moment to bind

        report = await validate_model_profile_async(
            profile_cfg,
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
        """GET /api/models/catalog - the live list; GET never refreshes (POST .../refresh does)."""
        require_api_access(request)
        payload = await refresher.current()
        return web.json_response(catalog_view(payload), dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_models_catalog_refresh(request: web.Request) -> web.Response:
        """POST /api/models/catalog/refresh - the picker's Check for new models button."""
        require_api_access(request)
        payload = await refresher.refresh()
        return web.json_response(catalog_view(payload), dumps=lambda x: json.dumps(x, ensure_ascii=False))

    app.router.add_get("/api/models", api_models)
    app.router.add_get("/api/models/catalog", api_models_catalog)
    app.router.add_post("/api/models/catalog/refresh", api_models_catalog_refresh)
    app.router.add_get("/api/models/capabilities", api_models_capabilities)
    app.router.add_get("/api/models/{profile}/ids", api_profile_models)
    app.router.add_get("/api/models/{profile}/handshake", api_profile_handshake)
    app.router.add_get("/api/models/{profile}/validate", api_profile_validate)
