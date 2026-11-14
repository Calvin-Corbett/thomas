"""The Token Economy routes, as a row: ``/api/spend/*`` and the two runtime settings routes beside them.

Off takes these routes away and ends the event stream an open page holds, and nothing else. The ledger they read is a
file, ``thomas_spend.jsonl``, so it stays, and the self-upgrade loop goes on adding to it and checking its own limit
against it. The cost line in Chat counts tokens from each reply's own receipt and asks these routes only for its prices,
so with this off it shows tokens and no dollars.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Spend:
    name = "spend"
    inject = ("web",)
    imports = ("thomas.server.routes.spend",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.spend import register_spend_routes

        service = ctx["web"]
        register_spend_routes(
            service.view(ctx, streams=("/api/spend/stream",)),
            require_api_access=service.require_api_access,
        )


plugin = _Spend()
