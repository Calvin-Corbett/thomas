"""Log unusually slow built-in HTML responses without storing request data."""

from __future__ import annotations

import logging
import time

from aiohttp import web

log = logging.getLogger(__name__)
_PAGES = frozenset({"/", "/classic", "/mission", "/settings", "/companion"})
_SLOW_PAGE_MS = 2000


@web.middleware
async def page_response_timing(request: web.Request, handler):  # type: ignore[no-untyped-def]
    if request.method != "GET" or request.path not in _PAGES:
        return await handler(request)
    started = time.monotonic()
    response = await handler(request)
    elapsed_ms = (time.monotonic() - started) * 1000
    if response.status == 200 and elapsed_ms >= _SLOW_PAGE_MS:
        log.warning("Slow page response path=%s elapsed_ms=%d", request.path, elapsed_ms)
    return response
