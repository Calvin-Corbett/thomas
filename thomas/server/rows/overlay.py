"""The interface overlay, as a row: its three routes, and the splice that puts your saved changes into every page.

Off takes the routes away and stops the splice, so every page Thomas serves comes back as it ships, with none of your saved
changes in it. Nothing is deleted: the file of saved changes is not touched, and turning this on puts the splice back, so
the next page carries every change exactly as it was. Redesign's planner is not part of this row. It stays on, and it goes
on reading the saved file whether the row is on or not.

The splice is ``inject_overlay`` in ``thomas.server.app_middleware_helpers``. The row installs it with ``ctx.effect``, which
takes it back when the row stops or a press on it is refused. A server started with this off never imports the row, so the
splice is never installed and a page leaves unchanged. ``thomas.server.overlay.render`` holds a two-second copy of the view
at the top of the module, keyed on the file's modification time, so a copy left from before off cannot outlast a change.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Overlay:
    name = "overlay"
    inject = ("web",)
    imports = ("thomas.server.overlay.render", "thomas.server.routes.ui_overlay_routes")

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.app_middleware_helpers import use_overlay_injector
        from thomas.server.overlay.render import inject
        from thomas.server.routes.ui_overlay_routes import setup_overlay_routes

        service = ctx["web"]
        setup_overlay_routes(service.view(ctx), require_api_access=service.require_api_access)
        ctx.effect(use_overlay_injector(inject))


plugin = _Overlay()
