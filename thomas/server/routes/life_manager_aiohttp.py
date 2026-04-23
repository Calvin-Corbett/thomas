from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.server.app_keys import APP_CONFIG
from thomas.server.desktop_plugins import is_plugin_enabled

_STATE_VERSION = 1
_STATE_RELATIVE_PATH = Path(".thomas") / "plugins" / "life-manager" / "state.json"
_COLLECTIONS = {"tasks", "agenda", "habits", "goals"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _state_path(app: web.Application) -> Path:
    config = app[APP_CONFIG]
    return Path(config.memory.root_path) / _STATE_RELATIVE_PATH


def _default_state() -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "updated_at": _utc_now_iso(),
        "tasks": [],
        "agenda": [],
        "habits": [],
        "goals": [],
    }


def _read_state(app: web.Application) -> dict[str, Any]:
    path = _state_path(app)
    if not path.exists():
        return _default_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(payload, dict):
        return _default_state()
    state = _default_state()
    for key in state:
        if key in {"tasks", "agenda", "habits", "goals"} and isinstance(payload.get(key), list) or key in payload:
            state[key] = payload.get(key)
    return state


def _write_state(app: web.Application, state: dict[str, Any]) -> None:
    path = _state_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["version"] = _STATE_VERSION
    state["updated_at"] = _utc_now_iso()
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _require_life_manager_enabled(app: web.Application) -> None:
    config = app[APP_CONFIG]
    if not is_plugin_enabled(config, "life-manager"):
        raise web.HTTPNotFound(text="Life Manager is not installed or enabled")


def _read_json(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _normalize_collection(name: str) -> str:
    normalized = _safe_text(name).lower()
    if normalized not in _COLLECTIONS:
        raise web.HTTPNotFound(text="Unknown Life Manager collection")
    return normalized


def _item_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6)}"


def _normalize_completion_log(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = _safe_text(item)
        if text and text not in out:
            out.append(text)
    return out


def _validate_task(data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    title = _safe_text(data.get("title"))
    if not partial and not title:
        raise web.HTTPBadRequest(text="Task title is required")
    status = _safe_text(data.get("status") or "todo").lower()
    if status not in {"todo", "doing", "done"}:
        raise web.HTTPBadRequest(text="Task status must be todo, doing, or done")
    priority = _safe_text(data.get("priority") or "medium").lower()
    if priority not in {"low", "medium", "high"}:
        raise web.HTTPBadRequest(text="Task priority must be low, medium, or high")
    patch: dict[str, Any] = {}
    if title:
        patch["title"] = title
    if partial and "title" in data and not title:
        raise web.HTTPBadRequest(text="Task title cannot be empty")
    if "status" in data or not partial:
        patch["status"] = status
    if "priority" in data or not partial:
        patch["priority"] = priority
    if "target_date" in data or not partial:
        patch["target_date"] = _safe_text(data.get("target_date"))
    if "goal_id" in data or not partial:
        patch["goal_id"] = _safe_text(data.get("goal_id"))
    return patch


def _validate_agenda(data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    title = _safe_text(data.get("title"))
    if not partial and not title:
        raise web.HTTPBadRequest(text="Agenda title is required")
    status = _safe_text(data.get("status") or "planned").lower()
    if status not in {"planned", "done", "canceled"}:
        raise web.HTTPBadRequest(text="Agenda status must be planned, done, or canceled")
    patch: dict[str, Any] = {}
    if title:
        patch["title"] = title
    if partial and "title" in data and not title:
        raise web.HTTPBadRequest(text="Agenda title cannot be empty")
    if "date" in data or not partial:
        patch["date"] = _safe_text(data.get("date"))
    if "start_time" in data or not partial:
        patch["start_time"] = _safe_text(data.get("start_time"))
    if "end_time" in data or not partial:
        patch["end_time"] = _safe_text(data.get("end_time"))
    if "status" in data or not partial:
        patch["status"] = status
    if "linked_task_id" in data or not partial:
        patch["linked_task_id"] = _safe_text(data.get("linked_task_id"))
    return patch


def _validate_habit(data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    title = _safe_text(data.get("title"))
    if not partial and not title:
        raise web.HTTPBadRequest(text="Habit title is required")
    cadence = _safe_text(data.get("cadence") or "daily").lower()
    if cadence not in {"daily", "weekly", "monthly"}:
        raise web.HTTPBadRequest(text="Habit cadence must be daily, weekly, or monthly")
    try:
        target_count = int(data.get("target_count", 1 if not partial else 0))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Habit target_count must be an integer") from None
    if not partial and target_count < 1:
        raise web.HTTPBadRequest(text="Habit target_count must be at least 1")
    patch: dict[str, Any] = {}
    if title:
        patch["title"] = title
    if partial and "title" in data and not title:
        raise web.HTTPBadRequest(text="Habit title cannot be empty")
    if "cadence" in data or not partial:
        patch["cadence"] = cadence
    if "target_count" in data or not partial:
        if target_count < 1:
            raise web.HTTPBadRequest(text="Habit target_count must be at least 1")
        patch["target_count"] = target_count
    if "completion_log" in data or not partial:
        patch["completion_log"] = _normalize_completion_log(data.get("completion_log"))
    return patch


def _validate_goal(data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    title = _safe_text(data.get("title"))
    if not partial and not title:
        raise web.HTTPBadRequest(text="Goal title is required")
    status = _safe_text(data.get("status") or "active").lower()
    if status not in {"active", "paused", "done"}:
        raise web.HTTPBadRequest(text="Goal status must be active, paused, or done")
    progress_raw = data.get("progress", 0 if not partial else None)
    patch: dict[str, Any] = {}
    if title:
        patch["title"] = title
    if partial and "title" in data and not title:
        raise web.HTTPBadRequest(text="Goal title cannot be empty")
    if "horizon" in data or not partial:
        patch["horizon"] = _safe_text(data.get("horizon") or "month")
    if "status" in data or not partial:
        patch["status"] = status
    if progress_raw is not None or not partial:
        try:
            progress = int(progress_raw if progress_raw is not None else 0)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Goal progress must be an integer") from None
        if progress < 0 or progress > 100:
            raise web.HTTPBadRequest(text="Goal progress must be between 0 and 100")
        patch["progress"] = progress
    if "notes" in data or not partial:
        patch["notes"] = _safe_text(data.get("notes"))
    return patch


def _normalize_patch(collection: str, data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    if collection == "tasks":
        return _validate_task(data, partial=partial)
    if collection == "agenda":
        return _validate_agenda(data, partial=partial)
    if collection == "habits":
        return _validate_habit(data, partial=partial)
    return _validate_goal(data, partial=partial)


def _collection_prefix(collection: str) -> str:
    return {"tasks": "task", "agenda": "agenda", "habits": "habit", "goals": "goal"}[collection]


def _collection_items(state: dict[str, Any], collection: str) -> list[dict[str, Any]]:
    items = state.get(collection)
    return items if isinstance(items, list) else []


def _build_item(collection: str, data: dict[str, Any]) -> dict[str, Any]:
    now = _utc_now_iso()
    item = {
        "id": _item_id(_collection_prefix(collection)),
        "created_at": now,
        "updated_at": now,
    }
    item.update(_normalize_patch(collection, data, partial=False))
    return item


def register_life_manager_routes(
    app: web.Application,
    *,
    require_api_access,
) -> None:
    async def api_life_manager_bootstrap(request: web.Request) -> web.Response:
        require_api_access(request)
        _require_life_manager_enabled(app)
        state = _read_state(app)
        return web.json_response({"ok": True, "state": state})

    async def api_life_manager_collection(request: web.Request) -> web.Response:
        require_api_access(request)
        _require_life_manager_enabled(app)
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

    async def api_life_manager_item(request: web.Request) -> web.Response:
        require_api_access(request)
        _require_life_manager_enabled(app)
        collection = _normalize_collection(request.match_info.get("collection", ""))
        item_id = _safe_text(request.match_info.get("item_id"))
        if not item_id:
            raise web.HTTPBadRequest(text="item_id is required")
        state = _read_state(app)
        items = _collection_items(state, collection)
        index = next((idx for idx, row in enumerate(items) if _safe_text(row.get("id")) == item_id), -1)
        if index < 0:
            raise web.HTTPNotFound(text="Life Manager item not found")
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

    app.router.add_get("/api/plugins/life-manager/bootstrap", api_life_manager_bootstrap)
    app.router.add_route("*", "/api/plugins/life-manager/{collection}", api_life_manager_collection)
    app.router.add_route("*", "/api/plugins/life-manager/{collection}/{item_id}", api_life_manager_item)
