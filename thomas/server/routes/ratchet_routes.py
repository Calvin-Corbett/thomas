"""GET /api/ratchet (every candidate's state and reason) and POST /api/ratchet/run (start a run now).

Registered by the ``ratchet`` row (``thomas/server/rows/ratchet.py``), which owns the
service these read and starts its daily loop. The POST is checked by the server's
mutating-route middlewares (auth and same-origin) like every other POST under
/api/; it starts the run in the background and answers 202, because a run lasts as
long as its proofs, repairs and your card do.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from aiohttp import web

APP_RATCHET = web.AppKey("ratchet", object)


def register_ratchet_routes(
    app: web.Application, *, service: Any, require_api_access: Callable[[web.Request], Any]
) -> None:
    from thomas.server.app_keys import local_port, remember_port
    from thomas.server.ratchet.service import DEFAULT_LIMIT, host_refusal

    app[APP_RATCHET] = service

    async def get_ratchet(request: web.Request) -> web.Response:
        require_api_access(request)
        return web.json_response(await asyncio.to_thread(service.report))

    async def run_ratchet(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            raw = await request.read()
            body = json.loads(raw.decode("utf-8-sig")) if raw.strip() else {}
            body = body if isinstance(body, dict) else {}
            limit = max(1, int(body.get("limit") or DEFAULT_LIMIT))
        except (ValueError, TypeError, UnicodeDecodeError):
            problem = {"error": 'the body must be JSON like {"limit": 3}', "code": "bad_request"}
            return web.json_response(problem, status=400)
        refusal = host_refusal()
        if refusal:
            return web.json_response({"error": refusal, "code": "ratchet_not_here"}, status=409)
        remember_port(request.app, local_port(request))
        if not service.launch(limit=limit, chat=str(body.get("chat_session_id") or "")):
            return web.json_response({"error": "a ratchet run is already going", "code": "ratchet_busy"}, status=409)
        return web.json_response({"status": "started", "limit": limit}, status=202)

    app.router.add_get("/api/ratchet", get_ratchet)
    app.router.add_post("/api/ratchet/run", run_ratchet)


__all__ = ["APP_RATCHET", "register_ratchet_routes"]
