"""Build, as a row: the 25 routes of the directed Code surface and the 8 of the self-upgrade loop dashboard.

The Build page, its conversations, files, previews and run controls are ``/api/evolve/agent/*``. The older Evolution
dashboard's loop and orchestration reads are ``/api/evolve/loop/*`` and ``/api/evolve/orchestration/*``. The frontier
panels that sit beside them (``agent_panels``) are a row of their own.

This row is required, so it has no off switch and loads whatever you saved. If it fails to start, Thomas keeps running,
the Plugins page shows it as failed with the reason, and Try again starts it. The handlers close over the real app and
write ``APP_EVOLVE_AGENT_*`` keys during requests, so they are built on ``service.app`` and only the route table goes to
the view. A second apply after a failed one is safe: the keys the handlers need are kept if they are there, and the ones
that are rebound (the start and stop calls Praxis reads) are written the same way each time. On an app that is already
running aiohttp accepts those writes with a deprecation warning.

The one thing here that outlives a request is the Thomas evolve processes the loop routes start and keep on the app.
When the row stops, at shutdown, they are ended. The two streams are named, so an open page cannot hold the stop.

The named calls Build provides (``evolve_agent_stop``) stay provided at import, never here. See
``thomas/server/rows/__init__.py`` for how a row is written.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

STREAMS = ("/api/evolve/agent/stream", "/api/evolve/agent/playtest/stream")


class _Build:
    name = "build"
    inject = ("web",)
    imports = ("thomas.server.routes.evolve_agent_routes", "thomas.server.routes.evolve_loop_routes")

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not callable(service.require_api_access):
            log.warning("Evolve loop routes unavailable: missing API access guard")
            raise RuntimeError("build has no access guard to register with")
        view = service.view(ctx, streams=STREAMS)
        try:
            from thomas.server.routes.evolve_agent_routes import register_evolve_agent_routes
            from thomas.server.routes.evolve_loop_routes import end_loop_processes, register_evolve_loop_routes

            register_evolve_loop_routes(service.app, require_api_access=service.require_api_access, routes_on=view)
            register_evolve_agent_routes(service.app, require_api_access=service.require_api_access, routes_on=view)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
            log.warning("Evolve loop routes unavailable: %s", exc)
            raise

        async def end_what_the_loop_started() -> None:
            await end_loop_processes(service.app)

        ctx.on_stopped(end_what_the_loop_started)


plugin = _Build()
