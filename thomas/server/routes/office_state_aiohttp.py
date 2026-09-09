"""Live Virtual Office shared-state HTTP API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.server.office_state import OfficeStateStore

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]


def register_office_state_routes(
    app: web.Application,
    *,
    root: str | Path,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    store = OfficeStateStore(root)

    def _user_id(request: web.Request) -> str:
        return str(request.headers.get("X-User-Id") or "").strip() or "default"

    async def get_state(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            state = store.get(user_id=_user_id(request))
        except (OSError, ValueError) as exc:
            raise web.HTTPInternalServerError(text="Office state read failed") from exc
        return web.json_response({"ok": True, "state": state})

    async def patch_state(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await read_json(request)
        if not isinstance(body, dict) or set(body) != {"follow_agent_id"}:
            raise web.HTTPBadRequest(text="follow_agent_id is the only supported Office field")
        try:
            state = store.set_follow_agent(body["follow_agent_id"], user_id=_user_id(request))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        except OSError as exc:
            raise web.HTTPInternalServerError(text="Office state update failed") from exc
        return web.json_response({"ok": True, "state": state})

    app.router.add_get("/api/office/state", get_state)
    app.router.add_patch("/api/office/state", patch_state)


__all__ = ["register_office_state_routes"]
