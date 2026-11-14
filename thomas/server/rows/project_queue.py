"""The queue of Thomas projects, as a row: the four ``/api/self/projects/queue`` routes the Improve Thomas window calls.

They list what is queued, queue a project to start later, and read and change the switch for Thomas planning and
starting improvements to itself. Off takes the four routes away and nothing else. The queue lives in a file in the
project catalog, and what starts a queued project, and what plans new ones, is a timer in the server that never calls
these routes, so both carry on while this is off.

The routes read the listing the project routes keep on the app. Those routes stay in the server, so the listing is
there whether this is on or off. Nothing here starts a thread or a task, so a stop has none to end.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _ProjectQueue:
    name = "project_queue"
    inject = ("web",)
    imports = ("thomas.server.routes.self_project_queue_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.self_project_queue_routes import register_self_project_queue_routes

        service = ctx["web"]
        register_self_project_queue_routes(service.view(ctx), require_loopback=service.require_loopback)


plugin = _ProjectQueue()
