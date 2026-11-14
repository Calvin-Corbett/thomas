"""GET /api/chat/cooldowns -> {"cooldowns": [{profile, remaining_s, failure_type}, ...]}.

The resting model profiles, longest wait first. The chat page asks when it opens
and after a failed turn, and shows a countdown (``rate_limit_banner.js``). A row
whose park was set by a spent allowance rather than a burst also carries
``account``, ``resets_at`` and ``resets_words``, so the page can say which limit
it is and when it resets instead of counting down the park's ten minutes -- and
is reported with ``remaining_s`` 0 once that park has lifted, because the
allowance behind it can be out for another day and a half. Registered by the
``cooldown_and_logs`` row.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.core.provider_cooldowns import limit_rows


def setup_cooldown_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], Any] | None = None,
) -> None:
    guard = require_api_access or (lambda _request: None)

    async def list_cooldowns(request: web.Request) -> web.Response:
        guard(request)
        return web.json_response({"cooldowns": limit_rows()})

    app.router.add_get("/api/chat/cooldowns", list_cooldowns)


__all__ = ["setup_cooldown_routes"]
