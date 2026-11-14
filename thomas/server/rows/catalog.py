"""The Marketplace page, the pages of the apps you installed, and the plugin store this Thomas can host, as a row.

Three registrars, and three things off takes away. ``/api/marketplace/*`` is the Marketplace page and the sidebar's list
of installed apps. ``/plugins/{plugin_id}/...`` and ``/app/{plugin_id}`` hand out those apps' pages.
``/api/v1/plugins/*`` is a store for other computers, with a folder and keys of its own. Off stops none of what is
underneath: what you installed stays on disk with its on or off setting, what an app saved and the routes that serve it
belong to the companion row, and the Settings page that turns this back on reads none of these routes.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _Catalog:
    name = "catalog"
    inject = ("web",)
    imports = (
        "thomas.server.routes.marketplace_catalog_aiohttp",
        "thomas.server.routes.plugin_hosting",
        "thomas.server.routes.standalone_app_aiohttp",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not callable(service.require_api_access):
            log.warning("Marketplace route registration skipped: missing runtime dependencies")
            raise RuntimeError("catalog has no access guard to register with")
        try:
            from thomas.server.routes.marketplace_catalog_aiohttp import register_marketplace_catalog_routes
            from thomas.server.routes.plugin_hosting import register_plugin_hosting_routes
            from thomas.server.routes.standalone_app_aiohttp import register_standalone_app_routes

            view = service.view(ctx)
            register_marketplace_catalog_routes(view, require_api_access=service.require_api_access)
            register_plugin_hosting_routes(view)
            register_standalone_app_routes(view, require_api_access=service.require_api_access)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
            log.warning("Marketplace routes unavailable: %s", exc)
            raise


plugin = _Catalog()
