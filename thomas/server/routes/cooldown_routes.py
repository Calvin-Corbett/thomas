"""GET /api/chat/cooldowns -> {"cooldowns": [{profile, remaining_s, failure_type}, ...]}.

The resting model profiles, longest wait first. The chat page asks after a
failed turn and shows a countdown (``rate_limit_banner.js``). Registered
from parity_routes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.core.provider_cooldowns import active_cooldowns


def setup_cooldown_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], Any] | None = None,
) -> None:
    guard = require_api_access or (lambda _request: None)

    async def list_cooldowns(request: web.Request) -> web.Response:
        guard(request)
        return web.json_response({"cooldowns": active_cooldowns()})

    app.router.add_get("/api/chat/cooldowns", list_cooldowns)


__all__ = ["setup_cooldown_routes"]
