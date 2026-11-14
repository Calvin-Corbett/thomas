"""The page asks, the OS prompts, the server remembers.

``POST /api/security/elevate`` with ``{"dial": ..., "value": ...}`` shows a native
OS prompt on this machine and answers whether the owner approved. ``GET
/api/security/elevation`` answers what is approved in this process, so the menu
can drop a level the server will not honour.

Anything with API access may *ask* -- the owner's direction is that agents can
trigger these toggles, because the password is what protects them. So the one
thing this route guards against is being used to wear the owner down: a prompt
that keeps coming back until someone taps yes to make it stop. Only one prompt
is open at a time, and a declined dial stays quiet for a short while.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.server import dial_elevation

_JSON_BODY_ERRORS = (json.JSONDecodeError, TypeError, UnicodeDecodeError)

# After a "no", the same dial cannot prompt again for this long.
DECLINE_COOLDOWN_S = 30.0

_APP_PROMPT_LOCK = web.AppKey("dial_elevation_prompt_lock", asyncio.Lock)
_APP_DECLINED_AT = web.AppKey("dial_elevation_declined_at", dict)


def setup_dial_elevation_routes(app: web.Application, *, require_api_access: Callable[[web.Request], None]) -> None:
    app[_APP_PROMPT_LOCK] = asyncio.Lock()
    app[_APP_DECLINED_AT] = {}

    async def elevate(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body: Any = await request.json()
        except _JSON_BODY_ERRORS:
            body = None
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "expected {dial, value}"}, status=400)
        dial = str(body.get("dial") or "").strip()
        value = body.get("value")
        if not dial_elevation.is_elevated(dial, value):
            # Either it needs no approval, or it is not a level at all. approve()
            # tells the two apart without prompting.
            approved = dial_elevation.approve(dial, value, authorize=lambda *_: False)
            return web.json_response({"ok": True, "approved": approved, "prompted": False})

        declined_at: dict[str, float] = request.app[_APP_DECLINED_AT]
        wait = DECLINE_COOLDOWN_S - (time.monotonic() - declined_at.get(dial, float("-inf")))
        if wait > 0:
            return web.json_response(
                {"ok": True, "approved": False, "prompted": False, "reason": "declined_recently", "retry_after": wait}
            )
        lock: asyncio.Lock = request.app[_APP_PROMPT_LOCK]
        if lock.locked():
            # Queueing would stack prompts on the owner's screen; answer instead.
            return web.json_response({"ok": True, "approved": False, "prompted": False, "reason": "prompt_open"})
        async with lock:
            # The prompt blocks until the owner answers, so it runs off the loop.
            loop = asyncio.get_running_loop()
            approved = await loop.run_in_executor(None, dial_elevation.approve, dial, value)
        if not approved:
            declined_at[dial] = time.monotonic()
        return web.json_response(
            {"ok": True, "approved": approved, "prompted": True, "grants": dial_elevation.grants()}
        )

    async def elevation(request: web.Request) -> web.Response:
        """What is approved, and -- for any dial named in the query -- the level
        the server would actually run it at. The menu uses the second part to stop
        showing a level it will not get: grants do not survive a restart, and a
        menu still reading "Autopilot" over a run at Agent would be a lie."""
        require_api_access(request)
        honoured = {
            dial: dial_elevation.cap(dial, value)
            for dial, value in request.query.items()
            if dial in ("autonomy", "file_access", "guardrails")
        }
        return web.json_response({"ok": True, "grants": dial_elevation.grants(), "honoured": honoured})

    app.router.add_post("/api/security/elevate", elevate)
    app.router.add_get("/api/security/elevation", elevation)
