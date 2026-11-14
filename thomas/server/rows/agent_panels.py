"""The agent panels, as a row: the 14 routes behind the top three sections of the Agent Ops page.

``/api/fleet/reply/*`` is Steer a running agent, ``/api/run-telemetry*`` is Live run telemetry and
``/api/worktree-progress/*`` is Worktree progress. The page itself is the server's, and so are its other three sections,
which the server and the mention_context row register.

Off takes these routes away and forgets all the three hold, because none of it lives anywhere but on a module, which stays
loaded after off. On starts them empty. Nothing in Thomas feeds them: only a program calling these routes does, and the
page's Seed demo button.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _AgentPanels:
    name = "agent_panels"
    inject = ("web",)
    imports = (
        "thomas.server.routes.fleet_reply_routes",
        "thomas.server.routes.run_telemetry_routes",
        "thomas.server.routes.worktree_progress_routes",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.fleet_reply_routes import register_fleet_reply_routes, reset_fleet_reply_service
        from thomas.server.routes.run_telemetry_routes import register_run_telemetry_routes, reset_run_projection
        from thomas.server.routes.worktree_progress_routes import (
            register_worktree_progress_routes,
            set_progress_aggregator,
        )

        service = ctx["web"]
        view = service.view(ctx)
        register_fleet_reply_routes(view, service.config, require_api_access=service.require_api_access)
        register_run_telemetry_routes(view, service.config)
        register_worktree_progress_routes(view, service.config)

        async def forget_what_they_held() -> None:
            reset_fleet_reply_service()
            reset_run_projection()
            set_progress_aggregator(None)

        ctx.on_stopped(forget_what_they_held)


plugin = _AgentPanels()
