"""A row that imports a module the shell keeps, and names nothing. The file is never loaded as a real row."""

from __future__ import annotations

from typing import Any


class _ImportsTheShell:
    name = "imports-the-shell"
    inject = ()

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.preferences_aiohttp import register_preferences_routes

        register_preferences_routes(ctx)


plugin = _ImportsTheShell()
