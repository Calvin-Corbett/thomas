"""The office state routes, as a row: ``GET`` and ``PATCH`` on ``/api/office/state``.

Off takes these two routes away and nothing else, and the Virtual Office shows it more than that suggests. The page paints
its older tile map only once a read of these routes succeeds, so with them gone it stays on its newer floor plan, where
following an agent moves nothing. The off test holds the row's words to that.

The agent they serve is kept in ``.thomas/office_state.json`` by ``thomas/server/office_state.py``, which no route here
owns. The Office chat reads and writes that file without these routes, so it goes on saving while the row is off, and
only the page loses its way to read it.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _OfficeState:
    name = "office_state"
    inject = ("web",)
    imports = ("thomas.server.routes.office_state_aiohttp",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.office_state_aiohttp import register_office_state_routes

        service = ctx["web"]
        register_office_state_routes(
            service.view(ctx),
            root=service.config.memory.root_path,
            require_api_access=service.require_api_access,
            read_json=service.read_json,
        )


plugin = _OfficeState()
