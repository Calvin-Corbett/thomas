"""The diagnostics routes, as a row: ``GET /api/engines``, ``GET /api/tools`` and ``GET /api/landing-health``.

Off takes these three routes away and nothing else. The engines and the tools they list are Thomas's own, so they go on
running and stay available to chat. The engine list is read from the server's engine manager, which the server keeps and
which the Idle awareness row also reports through. The Tools panel on the older full page and the command line's status
checks read these routes.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _ServerDiagnostics:
    name = "server_diagnostics"
    inject = ("web",)
    imports = ("thomas.server.server_diagnostics_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.server_diagnostics_routes import register_server_diagnostics_routes

        service = ctx["web"]
        register_server_diagnostics_routes(service.view(ctx), require_api_access=service.require_api_access)


plugin = _ServerDiagnostics()
