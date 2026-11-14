"""What your windows landed, as a row: ``GET /api/self/windows``, which lists your last windows, newest first.

It reads the record the promoter keeps of each window, and no page in Thomas calls it. Off takes the route away and
nothing else: the record is only ever read, so it stays as it is, and the Landed in line on a change's card comes from
the change itself and does not use this list. Nothing here starts a thread or a task, so a stop has none to end.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Windows:
    name = "windows"
    inject = ("web",)
    imports = ("thomas.server.window_records",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.window_records import register_window_routes

        service = ctx["web"]
        register_window_routes(service.view(ctx), require_loopback=service.require_loopback)


plugin = _Windows()
