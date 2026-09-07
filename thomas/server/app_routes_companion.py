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
    """Register /api/companion/v1/* (management, surface, generate) when the helpers exist."""
    if not callable(require_api_access) or not callable(read_json):
        log.warning("Companion route registration skipped: missing dependencies")
        return

    try:
        from thomas.server.routes.companion_aiohttp import register_companion_routes

        register_companion_routes(app, require_api_access=require_api_access, read_json=read_json, config=config)
    except _OPTIONAL_ROUTE_ERRORS as e:
        log.warning("Companion routes unavailable: %s", e)

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


__all__ = ["register_companion_route_family"]
