"""Who made the commits, as a row: ``GET /api/contributors`` and the Contributors section of Settings that reads it.

Off takes the one route away and nothing else. The counting only reads the history of the copy of Thomas you run and
writes nothing, so nothing is lost: turned back on, the same counts come back. The section stays in Settings and says
the counts are not available while this is off.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Contributors:
    name = "contributors"
    inject = ("web",)
    imports = ("thomas.server.routes.contributors", "thomas.core.contributors")

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.contributors import register_contributors_routes

        service = ctx["web"]
        register_contributors_routes(service.view(ctx), require_api_access=service.require_api_access)


plugin = _Contributors()
