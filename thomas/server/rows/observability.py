"""The observability routes, as a row: five that answer once, and ``/ws/events``, which stays open.

Off takes these routes away and drops anything connected to ``/ws/events``, and that is all. Agents and background tasks
go on keeping their own records, which ``thomas/core/agent_presence.py`` and ``thomas/core/task_bot_runtime.py`` write
with no help from here. No page in Thomas reads these routes. ``/api/events`` and the feed have nothing in them, because
nothing in Thomas calls ``record_event``, and ``/api/tools/usage`` always answers with the same empty figures. Mission
Control reads the same task records through a route of its own, so off does not reach it. ``uptime_seconds`` in
``/api/metrics`` counts from when the routes loaded, so on a server started with this off it counts from the first press
of on, and off and on does not reset it.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _Observability:
    name = "observability"
    inject = ("web",)
    imports = ("thomas.server.routes.observability",)

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not callable(service.require_api_access):
            log.warning("Observability routes unavailable: missing API access guard")
            raise RuntimeError("observability has no access guard to register with")
        try:
            from thomas.server.routes.observability import register_observability_routes

            register_observability_routes(
                service.view(ctx, streams=("/ws/events",)),
                require_api_access=service.require_api_access,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
            log.warning("Observability routes unavailable: %s", exc)
            raise


plugin = _Observability()
