"""The ratchet, as a row: the two ``/api/ratchet`` routes, the daily loop, and any run going.

Off takes the routes away and ends the loop. A run going holds the stop until it ends, because it counts as this row's
work, and Stop now cuts it short. What a run left stays safe: its records are in the ratchet's folder, a hand-in is the
promoter's, and a Build team is a run of its own, so the next run takes up each of them, and this row reaches none.

Chat's ``self.unlanded`` reads the same records with the row off. A card a run mirrors into a chat is followed by a plain
task, which goes on after off and ends with your answer, because the card it shows is the promoter's and is still real.
``thomas.server.ratchet`` holds nothing at the top level, so turning on builds a new service with nothing of the last.

Only the caged Thomas starts a run, and a release has no way to: there the routes answer from empty records and refuse.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Ratchet:
    name = "ratchet"
    inject = ("web",)
    imports = ("thomas.server.ratchet.service", "thomas.server.routes.ratchet_routes")

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.ratchet.service import RatchetService, autorun_enabled, host_refusal
        from thomas.server.routes.ratchet_routes import register_ratchet_routes

        service = ctx["web"]
        # The real app, not the view. A run reads keys the rest of the server keeps there and hands the app to Build's
        # start, and a key written through a view would leave with this row while that Build team ran on.
        ratchet = RatchetService(service.app, work=ctx)
        register_ratchet_routes(service.view(ctx), service=ratchet, require_api_access=service.require_api_access)
        if autorun_enabled() and not host_refusal():
            ctx.on_ready(ratchet.start)


plugin = _Ratchet()
