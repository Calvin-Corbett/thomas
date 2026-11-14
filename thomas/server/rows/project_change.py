"""A Thomas project's whole change, as a row: ``GET /api/self/projects/{conversation_id}/change``.

It reads what a project changed in its private copy, the files and the patch, without handing the project in and without
touching the copy, and it also works for a project that was stopped. No page in Thomas calls it. Off takes the route away
and nothing else: the project list, starting, sending back, handing in again and stopping stay in the server and carry on,
and nothing here starts a thread or a task, so a stop has none to end.

The route reads the projects through the module that keeps the other project routes. That module stays loaded whether
this is on or off, so the row's ``imports`` names the change module alone.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _ProjectChange:
    name = "project_change"
    inject = ("web",)
    imports = ("thomas.server.routes.self_project_change_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.self_project_change_routes import register_self_project_change_routes

        service = ctx["web"]
        register_self_project_change_routes(service.view(ctx), require_loopback=service.require_loopback)


plugin = _ProjectChange()
