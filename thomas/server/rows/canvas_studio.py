"""Canvas layouts, as a row: the five ``/api/canvas`` routes that save a layout, load it, turn it into code, and ask a
model for a layout.

Off takes those five routes away and nothing else. The folder the layouts are saved in, ``.thomas/canvas`` under the
project Thomas runs from, stays where it is and is read and written as before by the workspace helpers that save a
layout for an agent, through ``thomas/server/canvas_studio_shared.py``. The Canvas page works out its code in the
browser, so only its save button, its AI Template button and its sketch import ask these routes.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _CanvasStudio:
    name = "canvas_studio"
    inject = ("web",)
    imports = (
        "thomas.server.routes.canvas_studio_routes",
        "thomas.server.routes.canvas_studio_specgen",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.canvas_studio_routes import register_canvas_studio_routes

        service = ctx["web"]
        register_canvas_studio_routes(service.view(ctx), require_api_access=service.require_api_access)


plugin = _CanvasStudio()
