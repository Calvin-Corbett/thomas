"""aiohttp routes for UI workflow engine status, audits, effects, and assets."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from aiohttp import web

from thomas.core.ui_workflow_engine import get_ui_workflow_engine

log = logging.getLogger(__name__)

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]

_TRUE_BOOL_VALUES = {"1", "true", "yes", "on"}
_FALSE_BOOL_VALUES = {"0", "false", "no", "off"}


def _parse_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value == 1:
            return True
        if value == 0:
            return False
        raise ValueError("value must be boolean")
    if isinstance(value, float):
        raise ValueError("value must be boolean")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_BOOL_VALUES:
            return True
        if normalized in _FALSE_BOOL_VALUES:
            return False
    raise ValueError("value must be boolean")


def _parse_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("value must be integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            parsed = int(stripped)
        except ValueError as exc:
            raise ValueError("value must be integer") from exc
    else:
        raise ValueError("value must be integer")
    return max(minimum, min(maximum, parsed))


def _parse_providers(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [part.strip().lower() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("providers entries must be strings")
            raw.append(item.strip().lower())
    else:
        raise ValueError("providers must be a list or comma-separated string")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _parse_changed_paths(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("changed_paths entries must be strings")
            raw.append(item.strip())
    else:
        raise ValueError("changed_paths must be a list or comma-separated string")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        normalized = item.replace("\\", "/").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def register_ui_engine_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    def _engine():
        return get_ui_workflow_engine()

    async def api_ui_engine_status(request: web.Request) -> web.Response:
        require_api_access(request)
        engine = _engine()
        return web.json_response(
            {
                "ok": True,
                "status": engine.status_snapshot(),
                "last_report": engine.last_report(),
            }
        )

    async def api_ui_engine_effects(request: web.Request) -> web.Response:
        require_api_access(request)
        category = str(request.query.get("category") or "").strip().lower()
        engine = _engine()
        effects = engine.list_effects(category=category)
        return web.json_response(
            {
                "ok": True,
                "count": len(effects),
                "category": category,
                "effects": effects,
            }
        )

    async def api_ui_engine_audit_get(request: web.Request) -> web.Response:
        require_api_access(request)
        report = _engine().last_report()
        return web.json_response(
            {
                "ok": True,
                "has_report": bool(report),
                "report": report,
            }
        )

    async def api_ui_engine_audit_post(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")
        reason = str(payload.get("reason") or "manual").strip() or "manual"
        try:
            force = _parse_bool(payload.get("force"), default=False)
        except ValueError:
            log.warning("Invalid 'force' value for audit cycle", exc_info=True)
            raise web.HTTPBadRequest(text="invalid 'force' value")
        report = _engine().run_cycle_once(reason=reason, force=force)

        if not bool(report.get("ok", True)):
            reason_code = str(report.get("reason") or "").strip().lower()
            if reason_code == "engine_disabled":
                return web.json_response(report, status=503)
            if reason_code in {"busy", "not_idle"}:
                return web.json_response(report, status=409)
        return web.json_response(report)

    async def api_ui_engine_assets_search(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")

        query = str(payload.get("query") or payload.get("q") or "").strip()
        if len(query) < 2:
            raise web.HTTPBadRequest(text="query must be at least 2 characters")
        try:
            limit = _parse_int(payload.get("limit"), default=12, minimum=1, maximum=50)
        except ValueError:
            log.warning("Invalid 'limit' value for asset search", exc_info=True)
            raise web.HTTPBadRequest(text="invalid 'limit' value")

        providers: Iterable[str] | None = None
        if "providers" in payload:
            try:
                providers = _parse_providers(payload.get("providers"))
            except ValueError:
                log.warning("Invalid 'providers' value for asset search", exc_info=True)
                raise web.HTTPBadRequest(text="invalid 'providers' value")

        try:
            report = _engine().search_assets(query, limit=limit, providers=providers)
        except ValueError:
            log.warning("Asset search request was rejected", exc_info=True)
            raise web.HTTPBadRequest(text="invalid asset search request")
        return web.json_response(report)

    async def api_ui_engine_review(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")

        intent = str(payload.get("intent") or "").strip()
        try:
            strict = _parse_bool(payload.get("strict"), default=True)
        except ValueError:
            log.warning("Invalid 'strict' value for UI review", exc_info=True)
            raise web.HTTPBadRequest(text="invalid 'strict' value")
        changed_paths: Iterable[str] | None = None
        if "changed_paths" in payload:
            try:
                changed_paths = _parse_changed_paths(payload.get("changed_paths"))
            except ValueError:
                log.warning("Invalid 'changed_paths' value for UI review", exc_info=True)
                raise web.HTTPBadRequest(text="invalid 'changed_paths' value")

        report = _engine().review_ui_edits(intent=intent, changed_paths=changed_paths, strict=strict)
        verdict = str(report.get("verdict") or "").strip().lower()
        if verdict == "fail":
            return web.json_response(report, status=409)
        return web.json_response(report)

    app.router.add_get("/api/ui-engine/status", api_ui_engine_status)
    app.router.add_get("/api/ui-engine/effects", api_ui_engine_effects)
    app.router.add_get("/api/ui-engine/audit", api_ui_engine_audit_get)
    app.router.add_post("/api/ui-engine/audit", api_ui_engine_audit_post)
    app.router.add_post("/api/ui-engine/assets/search", api_ui_engine_assets_search)
    app.router.add_post("/api/ui-engine/review", api_ui_engine_review)
