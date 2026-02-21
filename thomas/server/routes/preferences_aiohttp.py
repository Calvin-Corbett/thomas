"""aiohttp route registration for settings/preferences UI persistence."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web
from pydantic import ValidationError

from thomas.preferences.store import PreferencesPatch, PreferencesResponse, PreferencesStore, get_db_path

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]


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
        return _prefs_json(store.get(user_id=user_id, thread_id=thread_id))

    async def api_preferences_patch(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            payload = await read_json(request)
        except web.HTTPBadRequest:
            payload = {}

        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")

        try:
            patch = PreferencesPatch(**payload)
        except ValidationError as exc:
            raise web.HTTPBadRequest(text=f"invalid preferences payload: {exc}") from exc

        store = _get_store()
        thread_id = _parse_thread_id(request)
        user_id = _get_user_id(request)
        try:
            updated = store.patch(patch=patch, user_id=user_id, thread_id=thread_id)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc

        return _prefs_json(updated)

    async def api_preferences_js(request: web.Request) -> web.StreamResponse:
        path = _prefs_settings_js()
        if not path.exists():
            raise web.HTTPNotFound(text="settings.js not found")
        return web.FileResponse(path)

    app.router.add_get("/api/preferences", api_preferences_get)
    app.router.add_patch("/api/preferences", api_preferences_patch)
    app.router.add_get("/js/settings.js", api_preferences_js)
