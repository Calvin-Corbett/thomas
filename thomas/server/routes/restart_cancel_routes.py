"""The route that calls off a restart which is still waiting for running work to finish."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiohttp import web


def register_restart_cancel_routes(app: Any, *, require_loopback: Callable[[web.Request], None]) -> None:
    """``POST /api/server/restart/cancel``: reopen task starts and resume held work; nothing running is stopped."""

    async def cancel(request: web.Request) -> web.Response:
        from thomas.server.owner_restart import cancel_restart

        require_loopback(request)
        return web.json_response({"ok": True, **await cancel_restart(request.app)})

    app.router.add_post("/api/server/restart/cancel", cancel)
