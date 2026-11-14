"""Scheduled tasks, as a row: the six ``/api/schedules`` routes and the thread that runs what is on the list.

Off takes the routes away and stops the ``TaskScheduler`` thread, so no task starts at its time. A run already going
carries on: the thread only hands each task to a pool, which starts a chat as a process of its own, and a stop neither
waits for that nor ends it. A task the pool holds for a free worker still starts. The list stays in
``.thomas/schedules.json``, where ``thomas cron`` goes on reading and changing it from a process of its own, and a new
scheduler reads that file when the row comes back, so a run that ends after a stop adds only its own record there. The
Mission queue keeps jobs of its own in a database, and nothing here touches them.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _Schedules:
    name = "schedules"
    inject = ("web",)
    imports = (
        "thomas.core.schedule_executor",
        "thomas.core.scheduler",
        "thomas.server.routes.schedule_routes",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.core.schedule_executor import install_scheduler
        from thomas.server.routes.schedule_routes import setup_schedule_routes

        service = ctx["web"]
        view = service.view(ctx)
        scheduler = install_scheduler(data_dir=Path(service.config.memory.root_path), auto_start=False, app=view)
        setup_schedule_routes(view, scheduler=scheduler, require_api_access=service.require_api_access)
        # Not a plain start. A row can still be refused for its routes after this returns, and at startup that throws it
        # away with no stop, so a thread begun by then would go on firing tasks with the row reading off.
        ctx.on_ready(scheduler.start)


plugin = _Schedules()
