"""Manual controls for background engine actions."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiohttp import web

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]


def _parse_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _normalize_engine_name(raw: Any) -> str:
    name = str(raw or "").strip().lower()
    aliases = {
        "issues": "code_issue_engine",
        "code_issue": "code_issue_engine",
        "code_issue_engine": "code_issue_engine",
        "upgrade": "self_upgrade_engine",
        "self_upgrade": "self_upgrade_engine",
        "self_upgrade_engine": "self_upgrade_engine",
        "ui": "ui_workflow_engine",
        "ui_workflow": "ui_workflow_engine",
        "ui_workflow_engine": "ui_workflow_engine",
        "sync": "workspace_sync_engine",
        "workspace_sync": "workspace_sync_engine",
        "workspace_sync_engine": "workspace_sync_engine",
    }
    return aliases.get(name, name)


def register_engine_actions_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    """Register endpoint for user-triggered engine actions."""

    def _unsupported(engine_name: str) -> bool:
        return engine_name not in {
            "code_issue_engine",
            "self_upgrade_engine",
            "ui_workflow_engine",
            "workspace_sync_engine",
        }

    async def api_engine_actions(request: web.Request) -> web.Response:
        require_api_access(request)
        payload = await read_json(request)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be a JSON object")

        engine = _normalize_engine_name(payload.get("engine"))
        if not engine:
            raise web.HTTPBadRequest(text="payload.engine is required")
        if _unsupported(engine):
            return web.json_response(
                {
                    "ok": False,
                    "engine": engine,
                    "error": f"unsupported engine: {engine}",
                },
                status=400,
            )

        action = str(payload.get("action") or "run").strip().lower()
        force = _parse_bool(payload.get("force"), default=False)
        reason = str(payload.get("reason") or "manual").strip() or "manual"

        if action not in {"run", "run_once"}:
            return web.json_response(
                {
                    "ok": False,
                    "engine": engine,
                    "error": f"unsupported action: {action}",
                },
                status=400,
            )

        try:
            if engine == "code_issue_engine":
                from thomas.core.code_issue_engine import get_code_issue_engine

                runner = get_code_issue_engine()
            elif engine == "self_upgrade_engine":
                from thomas.core.self_upgrade_engine import get_self_upgrade_engine

                runner = get_self_upgrade_engine()
            elif engine == "ui_workflow_engine":
                from thomas.core.ui_workflow_engine import get_ui_workflow_engine

                runner = get_ui_workflow_engine()
            elif engine == "workspace_sync_engine":
                from thomas.core.workspace_sync_engine import get_workspace_sync_engine

                runner = get_workspace_sync_engine()
            else:
                return web.json_response(
                    {"ok": False, "engine": engine, "error": f"unsupported engine: {engine}"},
                    status=400,
                )

            result = runner.run_cycle_once(force=force, reason=reason)
        except Exception as exc:
            return web.json_response(
                {
                    "ok": False,
                    "engine": engine,
                    "error": "engine run failed",
                    "exception": f"{type(exc).__name__}: {exc}",
                },
                status=500,
            )

        if not isinstance(result, dict):
            return web.json_response(
                {
                    "ok": False,
                    "engine": engine,
                    "error": "engine returned invalid result",
                },
                status=500,
            )

        ok = bool(result.get("ok", True))
        reason_code = str(result.get("reason") or "").strip().lower()
        if not ok:
            if reason_code in {"engine_disabled"}:
                status = 503
            elif reason_code in {"busy", "not_idle", "rate_limited"}:
                status = 409
            else:
                status = 400
        else:
            status = 200

        return web.json_response(
            {
                "ok": ok,
                "engine": engine,
                "action": action,
                "force": bool(force),
                "reason": reason,
                "result": result,
            },
            status=status,
        )

    app.router.add_post("/api/engine-actions", api_engine_actions)
