"""The display kernel's two routes: which block types are switched off, and a way to switch one.

``GET /api/display/types`` answers ``{"disabled": ["table", ...]}``. ``POST /api/display/types/{type}`` takes
``{"enabled": true|false}`` and answers the same. The list is :mod:`thomas.core.display_types`, a file in the data folder.
The browser reads it once when a page opens, and draws a switched-off type as the plain words its block carries.
"""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from thomas.core import display_types
from thomas.core.event_loop_offload import off_loop


def register_display_routes(app: Any, *, require_api_access: Any) -> None:
    """Register both routes on ``app`` (a row's view), each guarded with ``require_api_access``."""

    async def read(request: web.Request) -> web.Response:
        require_api_access(request)
        return web.json_response({"disabled": await off_loop("display.types", display_types.disabled)})

    async def switch(request: web.Request) -> web.Response:
        require_api_access(request)
        name = request.match_info["type"]
        try:
            body = json.loads(await request.text() or "null")
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
            return web.json_response({"error": 'send {"enabled": true} or {"enabled": false}'}, status=400)
        try:
            off = await off_loop("display.switch", display_types.set_enabled, name, body["enabled"])
        except ValueError as exc:
            # The refusal names what was sent, so a page can say which type it could not switch, not only why.
            return web.json_response({"error": str(exc), "type": name}, status=400)
        return web.json_response({"disabled": off})

    app.router.add_get("/api/display/types", read)
    app.router.add_post("/api/display/types/{type}", switch)
