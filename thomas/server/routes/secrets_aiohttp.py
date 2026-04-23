"""aiohttp route registration for secrets/API-key management."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from thomas.core.config import AppConfig
from thomas.server.app_keys import APP_CONFIG, APP_SECRETS
from thomas.server.secrets import SecretStore

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]


def _parse_bool(value: Any, *, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def register_secrets_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    async def api_secrets(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        secrets: SecretStore = request.app[APP_SECRETS]
        reminder_rows = secrets.rotation_reminders()
        reminders_by_profile = {
            str(item.get("profile") or ""): item for item in reminder_rows if isinstance(item, dict)
        }
        profiles = []
        for name, m in cfg.models.items():
            meta = secrets.metadata(name)
            reminder = reminders_by_profile.get(name, {})
            source = "secret_store" if secrets.get(name) else ("config" if m.api_key else "none")
            custom_rotation_days = meta.get("rotation_days")
            has_custom_rotation = custom_rotation_days is not None
            profiles.append(
                {
                    "name": name,
                    "provider": m.provider,
                    "base_url": m.base_url,
                    "model": m.model,
                    "has_key": bool(secrets.get(name) or m.api_key),
                    "persisted": secrets.is_persisted(name),
                    "source": source,
                    "updated_at": str(meta.get("updated_at") or ""),
                    "rotation_days": reminder.get("rotation_days"),
                    "rotation_days_source": "profile" if has_custom_rotation else "default",
                    "rotation_status": str(reminder.get("status") or "unknown"),
                    "rotation_due_at": str(reminder.get("due_at") or ""),
                    "rotation_due_in_days": reminder.get("due_in_days"),
                }
            )
        return web.json_response(
            {
                "storage": secrets.storage_info.__dict__,
                "profiles": profiles,
                "rotation": {
                    "default_rotation_days": 90,
                    "warning_days": 14,
                },
            }
        )

    async def api_secrets_reminders(request: web.Request) -> web.Response:
        require_api_access(request)
        secrets: SecretStore = request.app[APP_SECRETS]

        default_rotation_days_raw = request.query.get("default_rotation_days", "90")
        warning_days_raw = request.query.get("warning_days", "14")
        try:
            default_rotation_days = int(default_rotation_days_raw)
        except Exception:
            raise web.HTTPBadRequest(text="default_rotation_days must be an integer")
        try:
            warning_days = int(warning_days_raw)
        except Exception:
            raise web.HTTPBadRequest(text="warning_days must be an integer")

        try:
            reminders = secrets.rotation_reminders(
                default_rotation_days=default_rotation_days,
                warning_days=warning_days,
            )
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))

        summary = {
            "expired": 0,
            "due_soon": 0,
            "ok": 0,
            "unknown": 0,
        }
        for row in reminders:
            status = str(row.get("status") or "unknown").lower()
            if status not in summary:
                status = "unknown"
            summary[status] += 1

        return web.json_response(
            {
                "ok": True,
                "default_rotation_days": int(default_rotation_days),
                "warning_days": int(max(0, warning_days)),
                "summary": summary,
                "count": len(reminders),
                "reminders": reminders,
            }
        )

    async def api_secret_set(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        secrets: SecretStore = request.app[APP_SECRETS]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")

        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="json body must be an object")
        api_key = str(payload.get("api_key") or "").strip()
        persist = _parse_bool(payload.get("persist"), default=True)
        if persist is None:
            raise web.HTTPBadRequest(text="persist must be a boolean")
        rotation_days = payload.get("rotation_days")
        if rotation_days is not None:
            try:
                rotation_days = int(rotation_days)
            except Exception:
                raise web.HTTPBadRequest(text="rotation_days must be an integer")
        if not api_key:
            raise web.HTTPBadRequest(text="missing api_key")

        try:
            secrets.set(profile, api_key, persist=persist, rotation_days=rotation_days)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        meta = secrets.metadata(profile)
        return web.json_response(
            {
                "ok": True,
                "profile": profile,
                "persisted": persist,
                "updated_at": str(meta.get("updated_at") or ""),
                "rotation_days": meta.get("rotation_days"),
            }
        )

    async def api_secret_clear(request: web.Request) -> web.Response:
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        secrets: SecretStore = request.app[APP_SECRETS]
        profile = request.match_info["profile"]
        if profile not in cfg.models:
            raise web.HTTPNotFound(text="unknown profile")
        secrets.clear(profile)
        return web.json_response({"ok": True, "profile": profile})

    app.router.add_get("/api/secrets", api_secrets)
    app.router.add_get("/api/secrets/reminders", api_secrets_reminders)
    app.router.add_post("/api/secrets/{profile}", api_secret_set)
    app.router.add_delete("/api/secrets/{profile}", api_secret_clear)
