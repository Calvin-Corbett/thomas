"""Upkeep jobs on request, as a row: the one route through which another program starts an upkeep job.

Off takes that route away and nothing else. The four jobs stay in ``thomas/core``, and whether each also runs by itself
is settled when the server starts, so this row neither starts nor stops them. What a job has written stays: the upgrade
goals in Thomas's state, and what it saved to git. A running job is on a worker thread that cannot be cut short, so a
stop waits for it, and Stop now ends the wait and leaves the job running.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _EngineActions:
    name = "engine_actions"
    inject = ("web",)
    imports = ("thomas.server.routes.engine_actions_aiohttp",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.engine_actions_aiohttp import register_engine_actions_routes

        service = ctx["web"]
        register_engine_actions_routes(
            service.view(ctx),
            require_api_access=service.require_api_access,
            read_json=service.read_json,
        )


plugin = _EngineActions()
