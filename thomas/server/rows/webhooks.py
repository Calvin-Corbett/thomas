"""The webhook routes, as a row: the three receivers under ``/webhooks/receive/`` and the nine that manage them.

Off takes these routes away and nothing else. A delivery sent while it is off answers 404 and is not kept. The list of
webhooks, the inbox, the stats and the receipts stay in their files, where ``thomas webhooks`` in a terminal goes on
reading and changing them, because it opens those files itself and never asks a route. Webhooks Thomas sends out are
separate: alerts, the Asset Studio and the outgoing channels use none of this.

Whether a receiver must refuse an unsigned delivery is worked out here and held in ``routes/webhooks.py``, so it survives
off and on, and each turn on sets it again from the same setting.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Webhooks:
    name = "webhooks"
    inject = ("web",)
    imports = ("thomas.server.routes.webhooks_aiohttp",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.webhooks_aiohttp import register_webhooks_routes

        service = ctx["web"]
        mode = str(getattr(getattr(service.config, "server", None), "access_mode", "local") or "local").strip().lower()
        register_webhooks_routes(
            service.view(ctx),
            require_api_access=service.require_api_access,
            signature_enforcement_default=True if mode == "remote" else None,
        )


plugin = _Webhooks()
