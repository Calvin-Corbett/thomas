"""The setup routes, as a row: what Easy Setup is told about this computer, and the jobs it starts.

Off takes these eight routes away, and that is all. Easy Setup is part of the older full page, so it still opens, without
what ``/api/setup/bootstrap`` tells it, and its Local Ollama path cannot get past the third step. Keys, settings and models
stay where they are, and ``thomas/core/engine_manager.py`` goes on running the local background engine with no help from
here. A Thomas past Easy Setup asks these routes for nothing.

Three routes can run for a long time. ``/api/local/pull`` streams a download, so it is named in ``streams=`` and a stop ends
it. ``/api/local/sync`` can download for as long and answers once, so a stop waits for it, and Stop now drops the download.
``/api/setup/repair`` runs ``scripts/repair.ps1`` on a worker thread for up to half an hour, so a stop waits for that too,
even after the page has given up on it, and Stop now leaves the script running.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _Setup:
    name = "setup"
    inject = ("web",)
    imports = ("thomas.server.routes.setup_aiohttp", "thomas.server.routes.setup_local_sync")

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not all(
            callable(need) for need in (service.require_api_access, service.require_loopback, service.read_json)
        ):
            log.warning("Setup route registration skipped: missing runtime dependencies")
            raise RuntimeError("setup has no access guard or body reader to register with")
        try:
            from thomas.server.routes.setup_aiohttp import register_setup_routes

            register_setup_routes(
                service.view(ctx, streams=("/api/local/pull",)),
                require_api_access=service.require_api_access,
                require_loopback=service.require_loopback,
                read_json=service.read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
            log.warning("Setup routes unavailable: %s", exc)
            raise


plugin = _Setup()
