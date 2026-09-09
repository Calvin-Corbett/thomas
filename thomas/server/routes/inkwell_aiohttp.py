"""Inkwell smart-notepad plugin API.

Local-first state (notes with free-form text blocks + mouse-drawn ink
strokes, plus scheduled reminders) persisted as JSON under
``.thomas/plugins/inkwell/state.json`` — the same storage pattern as the
Life Manager command center. The ``/analyze`` endpoint asks the active
Thomas model to extract reminders and suggestions from raw note text.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.server.app_keys import APP_CONFIG
from thomas.server.desktop_plugins import is_plugin_enabled
from thomas.server.routes import inkwell_smart

_STATE_VERSION = 1
# State must live OUTSIDE the installed-plugin dir: plugin install/upgrade
# rmtree's .thomas/plugins/<id>/, which would delete the user's notes.
_STATE_RELATIVE_PATH = Path(".thomas") / "plugin-data" / "inkwell" / "state.json"
_LEGACY_STATE_RELATIVE_PATH = Path(".thomas") / "plugins" / "inkwell" / "state.json"
_COLLECTIONS = {"notes", "reminders", "insights"}
_INSIGHT_KINDS = {"category", "observation", "reminder_pile", "purpose"}
_DEFAULT_SETTINGS = {
    "auto_smart": True,  # the whole point of a SMART notepad: on by default
    "auto_create_reminders": True,
    "mic_silence_s": 8,
}
_REMINDER_SOUNDS = {"chime", "bell", "alarm", "pulse"}
_REMINDER_REPEATS = {"none", "daily", "weekly"}
_MAX_TEXT_LEN = 20_000
_MAX_BLOCKS = 200
_MAX_STROKES = 2_000
_MAX_POINTS_PER_STROKE = 4_000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _state_path(app: web.Application) -> Path:
    config = app[APP_CONFIG]
    return Path(config.memory.root_path) / _STATE_RELATIVE_PATH


def _default_state() -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "updated_at": _utc_now_iso(),
        "notes": [],
        "reminders": [],
        "insights": [],
        "settings": dict(_DEFAULT_SETTINGS),
    }


def _read_state(app: web.Application) -> dict[str, Any]:
    path = _state_path(app)
    if not path.exists():
        # One-time migration from the unsafe legacy location.
        config = app[APP_CONFIG]
        legacy = Path(config.memory.root_path) / _LEGACY_STATE_RELATIVE_PATH
        if legacy.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                return _default_state()
        else:
            return _default_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(payload, dict):
        return _default_state()
    state = _default_state()
    for key in _COLLECTIONS:
        items = payload.get(key)
        state[key] = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    saved_settings = payload.get("settings")
    if isinstance(saved_settings, dict):
        state["settings"].update({k: saved_settings[k] for k in _DEFAULT_SETTINGS if k in saved_settings})
    return state


def _write_state(app: web.Application, state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now_iso()
    path = _state_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _require_inkwell_enabled(app: web.Application) -> None:
    config = app[APP_CONFIG]
    if not is_plugin_enabled(config, "inkwell"):
        raise web.HTTPNotFound(text="Inkwell is not installed or enabled")


def _read_json(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _normalize_collection(name: str) -> str:
    collection = _safe_text(name).lower()
    if collection not in _COLLECTIONS:
        raise web.HTTPBadRequest(text=f"Unknown Inkwell collection: {collection or '(empty)'}")
    return collection


def _collection_items(state: dict[str, Any], collection: str) -> list[dict[str, Any]]:
    items = state.get(collection)
    return items if isinstance(items, list) else []


def _normalize_blocks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    blocks: list[dict[str, Any]] = []
    for raw in value[:_MAX_BLOCKS]:
        if not isinstance(raw, dict):
            continue
        blocks.append(
            {
                "id": _safe_text(raw.get("id")) or secrets.token_hex(6),
                "x": float(raw.get("x") or 0),
                "y": float(raw.get("y") or 0),
                "w": float(raw.get("w") or 240),
                "h": float(raw.get("h") or 0),
                "text": str(raw.get("text") or "")[:_MAX_TEXT_LEN],
                "color": _safe_text(raw.get("color"), 32),
            }
        )
    return blocks


def _normalize_strokes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    strokes: list[dict[str, Any]] = []
    for raw in value[:_MAX_STROKES]:
        if not isinstance(raw, dict):
            continue
        points = raw.get("points")
        if not isinstance(points, list):
            continue
        clean_points = [
            [float(p[0]), float(p[1])]
            for p in points[:_MAX_POINTS_PER_STROKE]
            if isinstance(p, (list, tuple)) and len(p) >= 2
        ]
        strokes.append(
            {
                "tool": _safe_text(raw.get("tool"), 24) or "pen",
                "color": _safe_text(raw.get("color"), 32) or "#2b2b3d",
                "size": float(raw.get("size") or 3),
                "points": clean_points,
            }
        )
    return strokes


def _normalize_patch(collection: str, payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if collection == "insights":
        text = _safe_text(payload.get("text"), 300)
        if not text and not partial:
            raise web.HTTPBadRequest(text="Insight text is required")
        if text:
            patch["text"] = text
        kind = _safe_text(payload.get("kind"), 24).lower() or "observation"
        patch["kind"] = kind if kind in _INSIGHT_KINDS else "observation"
        patch["why"] = _safe_text(payload.get("why"), 300)
        patch["note_id"] = _safe_text(payload.get("note_id"), 64)
        return patch
    if collection == "notes":
        if "title" in payload or not partial:
            patch["title"] = _safe_text(payload.get("title"), 200) or ("Untitled page" if not partial else "")
        if "blocks" in payload or not partial:
            patch["blocks"] = _normalize_blocks(payload.get("blocks"))
        if "strokes" in payload or not partial:
            patch["strokes"] = _normalize_strokes(payload.get("strokes"))
        return patch
    # reminders
    if "title" in payload or not partial:
        title = _safe_text(payload.get("title"), 300)
        if not title and not partial:
            raise web.HTTPBadRequest(text="Reminder title is required")
        if title:
            patch["title"] = title
    if "when" in payload or not partial:
        patch["when"] = _safe_text(payload.get("when"), 64)
    if "sound" in payload or not partial:
        sound = _safe_text(payload.get("sound"), 24).lower() or "chime"
        patch["sound"] = sound if sound in _REMINDER_SOUNDS else "chime"
    if "repeat" in payload or not partial:
        repeat = _safe_text(payload.get("repeat"), 24).lower() or "none"
        patch["repeat"] = repeat if repeat in _REMINDER_REPEATS else "none"
    if "note_id" in payload or not partial:
        patch["note_id"] = _safe_text(payload.get("note_id"), 64)
    if "source" in payload or not partial:
        source = _safe_text(payload.get("source"), 24).lower() or "manual"
        patch["source"] = source if source in {"manual", "thomas"} else "manual"
    if "why" in payload or not partial:
        patch["why"] = _safe_text(payload.get("why"), 300)
    if "fired_at" in payload:
        patch["fired_at"] = _safe_text(payload.get("fired_at"), 64)
    return patch


def _build_item(collection: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = _utc_now_iso()
    item = {"id": secrets.token_hex(8), "created_at": now, "updated_at": now}
    if collection == "reminders":
        item["fired_at"] = ""
    item.update(_normalize_patch(collection, payload, partial=False))
    return item


def register_inkwell_routes(
    app: web.Application,
    *,
    require_api_access,
) -> None:
    async def api_inkwell_bootstrap(request: web.Request) -> web.Response:
        require_api_access(request)
        _require_inkwell_enabled(app)
        state = _read_state(app)
        return web.json_response({"ok": True, "state": state})

    async def api_inkwell_analyze(request: web.Request) -> web.Response:
        require_api_access(request)
        _require_inkwell_enabled(app)
        payload = _read_json(await request.json())
        text = str(payload.get("text") or "").strip()[:_MAX_TEXT_LEN]
        if not text:
            raise web.HTTPBadRequest(text="text is required")
        config = app[APP_CONFIG]
        try:
            analysis = await inkwell_smart.analyze_text(
                config,
                text,
                local_now=_safe_text(payload.get("local_now"), 64),
            )
        except inkwell_smart.SmartAnalysisUnavailable as e:
            return web.json_response({"ok": False, "error": str(e)}, status=503)
        return web.json_response({"ok": True, "analysis": analysis})

    async def api_inkwell_settings(request: web.Request) -> web.Response:
        require_api_access(request)
        _require_inkwell_enabled(app)
        state = _read_state(app)
        if request.method == "GET":
            return web.json_response({"ok": True, "settings": state["settings"]})
        payload = _read_json(await request.json())
        settings = state["settings"]
        if "auto_smart" in payload:
            settings["auto_smart"] = bool(payload.get("auto_smart"))
        if "auto_create_reminders" in payload:
            settings["auto_create_reminders"] = bool(payload.get("auto_create_reminders"))
        if "mic_silence_s" in payload:
            try:
                settings["mic_silence_s"] = max(3, min(60, int(payload.get("mic_silence_s"))))
            except (TypeError, ValueError):
                pass
        _write_state(app, state)
        return web.json_response({"ok": True, "settings": settings})

    async def api_inkwell_collection(request: web.Request) -> web.Response:
        require_api_access(request)
        _require_inkwell_enabled(app)
        collection = _normalize_collection(request.match_info.get("collection", ""))
        state = _read_state(app)
        if request.method == "GET":
            return web.json_response({"ok": True, "items": _collection_items(state, collection)})
        payload = _read_json(await request.json())
        item = _build_item(collection, payload)
        items = _collection_items(state, collection)
        items.insert(0, item)
        state[collection] = items
        _write_state(app, state)
        return web.json_response({"ok": True, "item": item}, status=201)

    async def api_inkwell_item(request: web.Request) -> web.Response:
        require_api_access(request)
        _require_inkwell_enabled(app)
        collection = _normalize_collection(request.match_info.get("collection", ""))
        item_id = _safe_text(request.match_info.get("item_id"))
        if not item_id:
            raise web.HTTPBadRequest(text="item_id is required")
        state = _read_state(app)
        items = _collection_items(state, collection)
        index = next((idx for idx, row in enumerate(items) if _safe_text(row.get("id")) == item_id), -1)
        if index < 0:
            raise web.HTTPNotFound(text="Inkwell item not found")
        if request.method == "DELETE":
            removed = items.pop(index)
            state[collection] = items
            _write_state(app, state)
            return web.json_response({"ok": True, "removed": removed})
        payload = _read_json(await request.json())
        patch = _normalize_patch(collection, payload, partial=True)
        current = dict(items[index])
        current.update(patch)
        current["updated_at"] = _utc_now_iso()
        items[index] = current
        state[collection] = items
        _write_state(app, state)
        return web.json_response({"ok": True, "item": current})

    app.router.add_get("/api/plugins/inkwell/bootstrap", api_inkwell_bootstrap)
    app.router.add_post("/api/plugins/inkwell/analyze", api_inkwell_analyze)
    app.router.add_route("*", "/api/plugins/inkwell/settings", api_inkwell_settings)
    app.router.add_route("*", "/api/plugins/inkwell/{collection}", api_inkwell_collection)
    app.router.add_route("*", "/api/plugins/inkwell/{collection}/{item_id}", api_inkwell_item)
