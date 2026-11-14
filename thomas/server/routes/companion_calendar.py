"""Read-only phone agenda for the Infinite phone app from version 1.5.0.

Its calendar code polls this route once a minute with a 40-second timeout. The
caller lives outside this repository, so this docstring records that contract.
Only each event's id, title, start, end and location leave the PC: at most 250
events in the next 30 days, with each field limited to 1,000 characters.
Access is checked first; results are cached for one minute and provider calls
time out after 35 seconds. This route lives here rather than in
companion_aiohttp.py because that module is over its line budget.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

CALENDAR_PATH = "/api/companion/v1/calendar"
DAYS_AHEAD = 30
MAX_EVENTS = 250
CACHE_SECONDS = 60
TIMEOUT_SECONDS = 35
RECONNECT_HINT = "Connect or reconnect your calendar provider in Thomas on your PC."
_PROVIDER_ERRORS = (asyncio.TimeoutError, TimeoutError, RuntimeError, OSError, ValueError, httpx.HTTPError)
log = logging.getLogger(__name__)


def _get_calendar_service() -> Any:
    from thomas.tools.email_calendar import _get_service

    return _get_service()


def public_events(rows: Any) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        raise ValueError("Invalid calendar response")
    fields = ("id", "title", "start", "end", "location")
    return [
        {field: str(row.get(field) or "")[:1000] for field in fields}
        for row in rows[:MAX_EVENTS]
        if isinstance(row, dict)
    ]


def register_companion_calendar_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    service_factory: Callable[[], Any] | None = None,
) -> None:
    cache: dict[str, Any] = {}
    lock = asyncio.Lock()

    async def load_agenda() -> dict[str, Any]:
        async with lock:
            now = time.monotonic()
            if not cache or now - cache["timestamp"] > CACHE_SECONDS:
                service = (service_factory or _get_calendar_service)()
                events = public_events(await service.calendar_list_events(days=DAYS_AHEAD))
                cache.update(
                    timestamp=time.monotonic(),
                    events=events,
                    provider=getattr(getattr(service, "config", None), "provider", ""),
                    synced_at=datetime.now(timezone.utc).isoformat(),
                )
            return {
                "connected": True,
                "events": cache["events"],
                "provider": cache["provider"],
                "synced_at": cache["synced_at"],
            }

    async def agenda(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            payload = await asyncio.wait_for(load_agenda(), timeout=TIMEOUT_SECONDS)
        except _PROVIDER_ERRORS as error:
            log.warning("Companion calendar unavailable: %s", type(error).__name__)
            return web.json_response(
                {
                    "connected": False,
                    "events": [],
                    "error": RECONNECT_HINT,
                    "code": "calendar_unavailable",
                },
                status=503,
                headers={"Cache-Control": "no-store"},
            )
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    app.router.add_get(CALENDAR_PATH, agenda)
