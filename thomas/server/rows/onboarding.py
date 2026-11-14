"""Onboarding measurements, as a row: the three ``/api/onboarding`` routes that take first-run events and report on them.

Off takes these three routes away, and that is all. First-run setup does not use them for anything it needs: its steps,
your answers and the point where it counts as finished are saved through the preferences routes, which are not part of
this row, and the Easy Setup checks have a row of their own. So a new install still opens setup, can finish it and can
skip it. What stops is the page's note of each step it reaches, which it sends and does not wait for, and the three
reads of those notes. The notes that were already kept stay where they are.

Nothing here keeps a thread, a process or a file open, so there is no stop step.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Onboarding:
    name = "onboarding"
    inject = ("web",)
    imports = ("thomas.server.routes.onboarding_aiohttp",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.onboarding_aiohttp import register_onboarding_routes

        service = ctx["web"]
        register_onboarding_routes(service.view(ctx), require_api_access=service.require_api_access)


plugin = _Onboarding()
