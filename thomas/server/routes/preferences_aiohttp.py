"""aiohttp route registration for settings/preferences UI persistence."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from aiohttp import web
from pydantic import ValidationError

try:
    from thomas.observability.event_recorder import record_event
except Exception:  # pragma: no cover - optional observability dependency

    def record_event(*_args, **_kwargs):
        return None


from thomas.preferences.store import PreferencesPatch, PreferencesResponse, PreferencesStore, get_db_path

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]
log = logging.getLogger(__name__)


def _prefs_store_for_path(db_path: str) -> PreferencesStore:
    return PreferencesStore(db_path=db_path)


@lru_cache(maxsize=8)
def _store_for_path(db_path: str) -> PreferencesStore:
    return _prefs_store_for_path(db_path)


def _get_store() -> PreferencesStore:
    return _store_for_path(get_db_path())


def _get_user_id(request: web.Request) -> str:
    raw = str(request.headers.get("X-User-Id") or "").strip()
    return raw if raw else "default"


def _prefs_json(payload: PreferencesResponse) -> web.Response:
    return web.json_response(payload.model_dump())


def _parse_thread_id(request: web.Request) -> str | None:
    raw = str(request.query.get("thread_id") or "").strip()
    return raw if raw else None


def _emit_onboarding_patch_telemetry(*, user_id: str, thread_id: str | None, patch: PreferencesPatch) -> None:
    if patch.onboarding is None:
        return
    fields_set = sorted(str(k) for k in patch.onboarding.model_fields_set)
    if not fields_set:
        return
    incoming = patch.onboarding.model_dump(exclude_unset=True)
    changed_fields = {k: incoming.get(k, None) for k in fields_set}
    run_id = thread_id or f"onboarding_prefs_{user_id}"
    try:
        record_event(
            "onboarding.preferences.patch",
            {
                "user_id": user_id,
                "thread_id": thread_id,
                "changed_onboarding_fields": changed_fields,
            },
            run_id=run_id,
        )
    except Exception as exc:
        log.debug("onboarding preferences telemetry emit failed: %s", exc)


def _prefs_settings_js() -> Path:
    web_root = Path(__file__).resolve().parents[1] / "web"
    candidates = [
        web_root / "js" / "settings.js",
        web_root / "settings.js",
        web_root / "static" / "settings.js",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def register_preferences_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    async def api_preferences_get(request: web.Request) -> web.Response:
        require_api_access(request)
        store = _get_store()
        thread_id = _parse_thread_id(request)
        user_id = _get_user_id(request)
        try:
            return _prefs_json(store.get(user_id=user_id, thread_id=thread_id))
        except Exception as exc:
            log.exception("preferences get failed for user=%s", user_id)
            raise web.HTTPInternalServerError(text="preferences read failed") from exc

    async def api_preferences_patch(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            payload = await read_json(request)
        except web.HTTPBadRequest:
            payload = {}

        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")

        advanced_payload = payload.get("advanced")
        if isinstance(advanced_payload, dict) and "security" in advanced_payload:
            raise web.HTTPBadRequest(text="advanced.security must be changed via dedicated /api/security/* routes")

        try:
            patch = PreferencesPatch(**payload)
        except ValidationError as exc:
            log.debug("preferences patch validation failed: %d error(s)", exc.error_count())
            raise web.HTTPBadRequest(text="invalid preferences payload") from exc

        store = _get_store()
        thread_id = _parse_thread_id(request)
        user_id = _get_user_id(request)
        try:
            updated = store.patch(patch=patch, user_id=user_id, thread_id=thread_id)
        except ValueError as exc:
            log.debug("preferences patch rejected for user=%s: %s", user_id, type(exc).__name__)
            raise web.HTTPBadRequest(text="invalid preferences payload") from exc
        except Exception as exc:
            log.exception("preferences patch failed for user=%s", user_id)
            raise web.HTTPInternalServerError(text="preferences update failed") from exc
        _emit_onboarding_patch_telemetry(user_id=user_id, thread_id=thread_id, patch=patch)

        return _prefs_json(updated)

    async def api_preferences_js(request: web.Request) -> web.StreamResponse:
        path = _prefs_settings_js()
        if not path.exists():
            raise web.HTTPNotFound(text="settings.js not found")
        return web.FileResponse(path)

    app.router.add_get("/api/preferences", api_preferences_get)
    app.router.add_patch("/api/preferences", api_preferences_patch)
    app.router.add_get("/js/settings.js", api_preferences_js)
