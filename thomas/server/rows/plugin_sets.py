"""Ready-made plugin sets, as a row: ``GET /api/plugins/sets`` and ``POST /api/plugins/sets/{id}/apply``.

Off takes both routes away and that is all. The switches themselves are the server's and carry on, and every plugin stays
as it was. The row starts no work and has no stop step: a set that is being applied when this is turned off carries on
until a stop, which waits for the request, or Stop now cuts it off part way.

The sets and headings are ``thomas/server/rows/sets.toml``, and the routes are in
``thomas/server/ready_made_sets.py``. ``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _PluginSets:
    name = "plugin_sets"
    inject = ("web",)
    imports = ("thomas.server.ready_made_sets",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.ready_made_sets import register_plugin_sets_routes

        service = ctx["web"]
        register_plugin_sets_routes(service, service.view(ctx))


plugin = _PluginSets()
