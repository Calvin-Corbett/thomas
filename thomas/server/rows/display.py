"""The display kernel's routes, as a row: the list of block types you have switched off, and the way to switch one.

Off takes both routes away and nothing else. The page keeps drawing every block type with its own renderer, because a page
that cannot read the list treats every type as on, and the file of types you switched off is not touched, so turning this
on puts the list back. The renderers themselves are plain files the page loads, and this row does not own them.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Display:
    name = "display"
    inject = ("web",)
    imports = ("thomas.server.routes.display_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.display_routes import register_display_routes

        service = ctx["web"]
        register_display_routes(service.view(ctx), require_api_access=service.require_api_access)


plugin = _Display()
