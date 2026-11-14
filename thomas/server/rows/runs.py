"""Run history, as a row: the ten ``/api/runs`` routes, which read back what the run store holds.

Off takes these routes away and ends any replay still being read, and that is all. The store stays the server's:
``thomas/server/app_core.py`` opens ``.thomas/runs.sqlite3`` as the server starts, chat goes on writing a run for each turn,
Mission Control goes on reading it directly, and the janitor in ``thomas/server/app_routes_init.py`` goes on closing runs
left open. No page you normally reach reads these routes. ``POST /api/runs/{run_id}/cancel`` only answers: it cancels
nothing, and that was so before it moved here.

The server opens the store under ``thomas.marketplace.observability.run_store``, and these routes load the same file a
second time as ``thomas.observability.run_store``, which has a database path of its own. So the registrar opens the store
again, on every press of on, and that second copy keeps its path through off.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Runs:
    name = "runs"
    inject = ("web",)
    imports = ("thomas.server.routes.runs",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.app_keys import APP_RUN_STORE_ENABLED
        from thomas.server.routes.runs import register_runs_routes

        service = ctx["web"]
        # The server set this before any row loaded. If the store did not open, these routes would read nothing, so the
        # row says so by reading failed, where a family in the shell left no sign but a line in the log.
        if not service.app.get(APP_RUN_STORE_ENABLED):
            raise RuntimeError("the run store did not open when the server started")
        view = service.view(ctx, streams=("/api/runs/{run_id}/replay", "/api/runs/{run_id}/replay_stream"))
        register_runs_routes(view, service.config)


plugin = _Runs()
