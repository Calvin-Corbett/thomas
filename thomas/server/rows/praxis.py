"""The Build run channel, as a row: the one route a Build run's helpers call back into, and the runs it keeps open.

Off takes the route away only once every open run has ended, because a run's helpers call this route for as long as
the run lasts and would meet a 404 in the middle of their work. Each open channel counts as this row's work until the
run closes or is suspended, so a stop waits for them. Stop now ends the wait: every channel still open is suspended,
and its progress stays in the run journal, so turning the row back on takes each interrupted run up again from it. The
routes of a run whose helpers are still going are gone by then, and a helper that calls in finds a 404.

The recovery of interrupted runs happens when the server is up, before the restart pass reads its report, and it is the
same scan whether it comes from a start of Thomas or from turning the row on. The registry of channels and that report
are kept on the view, so off clears both. ``thomas.server.praxis.launch`` reads the registry from the real app, so a
run that starts while the row is off has no channel.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import asyncio
from typing import Any


class _Praxis:
    name = "praxis"
    inject = ("web",)
    imports = (
        "thomas.server.praxis.run_channel",
        "thomas.server.praxis.startup",
        "thomas.server.routes.praxis_run_routes",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.praxis.startup import recover_interrupted_runs
        from thomas.server.routes.praxis_run_routes import register_praxis_run_routes

        service = ctx["web"]
        # Kept until running work has ended: a run's helpers call this route for as long as the run lasts.
        view = service.view(ctx, keep_routes=True)
        registry = register_praxis_run_routes(view, recover_at_startup=False)

        def hold(run_id: str) -> Any:
            over = asyncio.Event()

            async def held() -> None:
                async with ctx.busy():
                    await over.wait()

            ctx.task(held, name=f"run {run_id}")
            return over.set

        registry.holder = hold
        # Not a hook on the view: the server's start does not wait for those, and the restart pass reads this report.
        ctx.on_ready(lambda: recover_interrupted_runs(view, registry))


plugin = _Praxis()
