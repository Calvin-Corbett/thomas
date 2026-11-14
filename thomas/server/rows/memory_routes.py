"""The memory routes, as a row: ``/api/memory`` and the eight that hang off it.

Off takes these routes away and nothing else. They look into the memory engine the server builds as it starts, so what
Thomas remembers stays, and chat goes on reading and writing that engine directly. Pins, contradictions and curator
approvals stay as they are, and a decision nothing has made goes on waiting.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _MemoryRoutes:
    name = "memory_routes"
    inject = ("web",)
    imports = ("thomas.server.routes.memory_aiohttp",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.memory_aiohttp import register_memory_routes

        service = ctx["web"]
        register_memory_routes(
            service.view(ctx),
            require_api_access=service.require_api_access,
            read_json=service.read_json,
        )


plugin = _MemoryRoutes()
