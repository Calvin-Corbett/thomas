"""The Agents workspace, as a row: the page at ``/agents`` and the load history it charts from ``GET /api/agents/vitals``.

Off takes these routes away and stops the sampler that keeps ten minutes of CPU and memory. The task board reads the work
row's ``/api/mission/control``, so with work off the board is empty and the vitals still draw. Nothing is written to disk.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Agents:
    name = "agents"
    inject = ("web",)
    imports = ("thomas.server.agents_routes", "thomas.core.agent_vitals")

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.core.agent_vitals import HISTORY, sample_loop
        from thomas.server.agents_routes import register_agents_routes

        service = ctx["web"]
        register_agents_routes(
            service.view(ctx), web_dir=service.web_dir, require_api_access=service.require_api_access, history=HISTORY
        )
        ctx.on_ready(lambda: ctx.task(lambda: sample_loop(HISTORY), name="agents vitals sampler"))


plugin = _Agents()
