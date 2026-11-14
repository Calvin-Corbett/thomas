"""The goals routes, as a row: ``/api/goals`` and the five that hang off it.

Off takes these routes away and nothing else. The list they serve is saved with Thomas's state, so it stays, and the
self-upgrade engine goes on writing to it. The goals you set in chat are a different list, kept with each project by
``thomas/tools/goals.py``, and no route here reads it.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Goals:
    name = "goals"
    inject = ("web",)
    imports = ("thomas.server.routes.goals",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.goals import register_goals_routes

        service = ctx["web"]
        register_goals_routes(
            service.view(ctx),
            require_api_access=service.require_api_access,
            read_json=service.read_json,
        )


plugin = _Goals()
