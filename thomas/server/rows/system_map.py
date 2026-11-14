"""The System Map, as a row: the page at ``/system-map`` and the reading it shows from ``GET /api/system-map``.

Off takes these three routes away and nothing else. The reading is of git: the branches, the separate working copies
and the set-aside piles in this project. It is made when asked and kept nowhere, so nothing is lost. The sidebar's System
Map entry and the one in Chat open the page in a frame, so with this off they open a frame that reads 404.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _SystemMap:
    name = "system_map"
    inject = ("web",)
    imports = ("thomas.server.system_map_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.system_map_routes import register_system_map_routes

        service = ctx["web"]
        register_system_map_routes(
            service.view(ctx), web_dir=service.web_dir, require_api_access=service.require_api_access
        )


plugin = _SystemMap()
