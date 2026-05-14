"""Compatibility stub for legacy route-registration contract tests.

The active server wiring lives in ``thomas.server.app_routes_init``. This module keeps
legacy source-inspection checks pointed at the current route bundle names.
"""

from __future__ import annotations

from thomas.server.routes.life_manager_aiohttp import register_life_manager_routes
from thomas.server.routes.marketplace_catalog_aiohttp import register_marketplace_catalog_routes
from thomas.server.routes.plugin_hosting import register_plugin_hosting_routes

__all__ = [
    "register_marketplace_catalog_routes",
    "register_plugin_hosting_routes",
    "register_life_manager_routes",
]
