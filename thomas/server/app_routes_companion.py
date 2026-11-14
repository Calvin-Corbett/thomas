"""The companion route family, registered from ``app_routes_init``.

Three registrations (management, surface host and bridge, generate-an-app)
lived as nested functions inside ``_setup_routes_and_handlers``. That
function is a single 1,500-line body under the hard ceiling
``test_file_sizes`` enforces on every push; moving the family here is the
smallest honest split. Each registration is optional: a missing module or a
broken import logs a warning and the server keeps booting without it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from aiohttp import web

_OPTIONAL_ROUTE_ERRORS = (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError)


def register_companion_route_family(
    app: web.Application,
    config: Any,
    *,
    require_api_access: Callable[..., Any] | None,
    read_json: Callable[..., Any] | None,
    log: logging.Logger,
) -> None:
    """Register /api/companion/v1/* (management, phone calendar, surface, generate)."""
    if not callable(require_api_access) or not callable(read_json):
        log.warning("Companion route registration skipped: missing dependencies")
        return

    try:
        from thomas.server.routes.companion_aiohttp import register_companion_routes

        register_companion_routes(app, require_api_access=require_api_access, read_json=read_json, config=config)
    except _OPTIONAL_ROUTE_ERRORS as e:
        log.warning("Companion routes unavailable: %s", e)

    try:
        from thomas.server.routes.companion_calendar import register_companion_calendar_routes

        register_companion_calendar_routes(app, require_api_access=require_api_access)
    except _OPTIONAL_ROUTE_ERRORS as e:
        log.warning("Companion calendar route unavailable: %s", e)

    try:
        from thomas.server.routes.companion_surface_aiohttp import register_companion_surface_routes

        register_companion_surface_routes(
            app, require_api_access=require_api_access, read_json=read_json, config=config
        )
    except _OPTIONAL_ROUTE_ERRORS as e:
        log.warning("Companion surface routes unavailable: %s", e)

    try:
        from thomas.server.routes.companion_generate_aiohttp import register_companion_generate_routes

        register_companion_generate_routes(
            app, require_api_access=require_api_access, read_json=read_json, config=config
        )
    except _OPTIONAL_ROUTE_ERRORS as e:
        log.warning("Companion generate routes unavailable: %s", e)

    try:
        from thomas.server.routes.inkwell_aiohttp import register_inkwell_routes
        from thomas.server.routes.life_manager_aiohttp import register_life_manager_routes
        from thomas.server.routes.paper_trading_aiohttp import register_paper_trading_routes

        register_life_manager_routes(app, require_api_access=require_api_access)
        register_inkwell_routes(app, require_api_access=require_api_access)
        register_paper_trading_routes(app, require_api_access=require_api_access)
    except _OPTIONAL_ROUTE_ERRORS as e:
        log.warning("Companion app routes unavailable: %s", e)


class _CompanionPlugin:
    """The companion surface as a plugin: its routes arrive with it and leave with it."""

    name = "companion"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        register_companion_route_family(
            service.view(ctx),
            service.config,
            require_api_access=service.require_api_access,
            read_json=service.read_json,
            log=logging.getLogger(__name__),
        )


plugin = _CompanionPlugin()

__all__ = ["plugin", "register_companion_route_family"]
