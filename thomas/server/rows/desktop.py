"""The isolated desktop's setup routes, as a row: the six ``/api/onboarding/desktop`` routes and the helper.

Off takes the six routes away and stops the desktop helper if this Thomas started one. What the helper's setup saved
stays: the state file under the data folder, and the isolated desktop choices in your preferences. Nothing here uninstalls
the host service, and an install or a viewer already launched is a program of its own, which a stop neither waits for nor
ends. The Agents page stops listing the helper, and Easy Setup reports the isolated desktop as not enabled, because both
ask whether this row is on before they read it, and a server started with it off never loads the helper's code.

A module stays loaded after off. This row's stop step forgets the shared host service and the helper's manager, so
turning on builds new ones from the environment of that moment and finds nothing of the last.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import asyncio
from typing import Any


def _stop_the_helper() -> None:
    from thomas.desktop_operator.host_service import forget_global_desktop_host_service
    from thomas.desktop_operator.manager import stop_global_desktop_operator_manager

    stop_global_desktop_operator_manager()
    forget_global_desktop_host_service()


class _Desktop:
    name = "desktop"
    inject = ("web",)
    imports = (
        "thomas.server.routes.desktop_aiohttp",
        "thomas.desktop_operator.host_service",
        "thomas.desktop_operator.manager",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.desktop_aiohttp import register_desktop_routes

        service = ctx["web"]
        register_desktop_routes(service.view(ctx), require_api_access=service.require_api_access)

        async def stop_helper() -> None:
            # Ending the helper waits up to three seconds for it to exit, which must not hold the event loop.
            await asyncio.to_thread(_stop_the_helper)

        ctx.on_stopped(stop_helper)


plugin = _Desktop()
