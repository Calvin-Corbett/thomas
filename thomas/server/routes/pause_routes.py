"""Pause and Resume for everything Thomas starts by himself: three routes for one saved switch.

``GET /api/thomas/pause`` reads the switch, ``POST /api/thomas/pause`` turns it on (a JSON body may carry a
``reason``) and ``POST /api/thomas/resume`` turns it off. Each answers the same thing::

    {"paused": bool, "since": iso string or None, "reason": str, "still_running": int}

``still_running`` is how many Build and Code runs are going now, counted from the registry the capacity code reads.
Pausing does not end them.

The switch itself is :mod:`thomas.core.pause`, a file in the data folder. Every route asks for the API access token, so
a caller from another machine without one is refused with 401.
"""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from thomas.core import pause as pause_state
from thomas.core.event_loop_offload import off_loop
from thomas.server.routes.evolve_agent_run_state import active_code_runs


def _answer(app: web.Application, state: dict[str, Any]) -> web.Response:
    return web.json_response({**state, "still_running": len(active_code_runs(app))})


async def _reason(request: web.Request) -> str:
    """The reason in an optional JSON body. No body, or one that is not an object, is no reason."""
    try:
        body = json.loads(await request.text() or "null")
    except ValueError:
        return ""
    return str(body.get("reason") or "") if isinstance(body, dict) else ""


def register_pause_routes(app: Any, *, require_api_access: Any) -> None:
    """Register the three routes on ``app`` (a row's view), each guarded with ``require_api_access``."""

    async def read(request: web.Request) -> web.Response:
        require_api_access(request)
        return _answer(request.app, await off_loop("pause.state", pause_state.state))

    async def pause(request: web.Request) -> web.Response:
        require_api_access(request)
        reason = await _reason(request)
        return _answer(request.app, await off_loop("pause.pause", pause_state.pause, reason))

    async def resume(request: web.Request) -> web.Response:
        require_api_access(request)
        return _answer(request.app, await off_loop("pause.resume", pause_state.resume))

    app.router.add_get("/api/thomas/pause", read)
    app.router.add_post("/api/thomas/pause", pause)
    app.router.add_post("/api/thomas/resume", resume)
