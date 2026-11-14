"""Cancelling a waiting restart, as a row that is required: you must be able to say "not now" whatever else is off.

A restart you ask for waits for every running check, which can take an hour, and new tasks are held until it happens.
This row brings up one route, ``POST /api/server/restart/cancel``, which reopens task starts and resumes held work
through ``thomas.server.owner_restart.cancel_restart``. Nothing that was running is stopped, and nothing here starts a
thread or a task, so a stop has none to end. Asking for the restart itself stays with the server.

If it fails to start, Thomas keeps running, the Plugins page shows it as failed with the reason, and Try again starts it.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _RestartCancel:
    name = "restart_cancel"
    inject = ("web",)
    imports = ("thomas.server.routes.restart_cancel_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not callable(service.require_loopback):  # with no guard the route would answer another computer
            log.warning("Restart cancel route unavailable: missing this-computer-only guard")
            raise RuntimeError("restart_cancel has no this-computer-only guard to register with")
        from thomas.server.routes.restart_cancel_routes import register_restart_cancel_routes

        register_restart_cancel_routes(service.view(ctx), require_loopback=service.require_loopback)


plugin = _RestartCancel()
