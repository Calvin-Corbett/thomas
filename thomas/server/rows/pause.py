"""The Pause routes, as a row that is required: the switch has to work even when everything else is off.

Pause is the way to stop what Thomas starts by himself, so this row has no off switch. It loads whatever was saved, and
every way of turning it off is refused. What the row does is bring up three routes, ``GET /api/thomas/pause``,
``POST /api/thomas/pause`` and ``POST /api/thomas/resume``, which read and change the saved switch in
``thomas.core.pause``. Nothing here starts a thread or a task, so a stop has none to end.

If it fails to start, Thomas keeps running, the Plugins page shows it as failed with the reason, and Try again starts it.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _Pause:
    name = "pause"
    inject = ("web",)
    imports = ("thomas.server.routes.pause_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not callable(service.require_api_access):
            log.warning("Pause routes unavailable: missing API access guard")
            raise RuntimeError("pause has no access guard to register with")
        from thomas.server.routes.pause_routes import register_pause_routes

        register_pause_routes(service.view(ctx), require_api_access=service.require_api_access)


plugin = _Pause()
