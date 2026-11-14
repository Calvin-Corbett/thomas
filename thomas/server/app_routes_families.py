"""The optional route families, registered from ``app_routes_init``.

Gateway, frontier surfaces, third-party access, live plugin control,
and the rest below.
Each lived as a nested registrar inside ``_setup_routes_and_handlers``, a single
1,382-line function the seam finder could not cut between definitions; this is
the inner cut, made by hand along the same line the companion family already
took. Every family stays optional: a missing module logs a warning and the
server boots.

No count in this docstring: it said "fourteen" while the file held more than
twenty, because a number here has to be corrected by whoever adds a family and
silently goes stale when they do not. ``grep '^    def _register_'`` is the
answer that cannot drift.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.core.config import AppConfig
from thomas.server.app_keys import APP_RUN_STORE_ENABLED, APP_RUN_STORE_MODULE


def register_optional_route_families(
    app: web.Application,
    config: AppConfig,
    *,
    require_api_access: Callable[..., Any],
    read_json: Callable[..., Any],
    require_loopback: Callable[..., Any],
    model_cfg_with_secrets: Callable[..., Any],
    log: logging.Logger,
) -> None:
    """Register every family in the order the initializer always used."""
    _require_api_access = require_api_access
    _read_json = read_json
    _require_loopback = require_loopback
    _model_cfg_with_secrets = model_cfg_with_secrets

    def _install_gateway_auth(app_ref: web.Application) -> None:
        """Put the gateway's check of who may call in front of every path, whether or not the gateway routes are on.

        It stays here and not in the gateway row because ``gateway_auth_scope = all`` makes it refuse any path on the
        server that has no token, and aiohttp fixes its middleware list when the server starts. The gateway row refuses
        to start when this did not run, so the routes can never be open for want of it.
        """
        try:
            from thomas.server.routes.gateway.p136_gateway_auth_policy_enforcement import (
                gateway_auth_policy_middleware,
            )

            if gateway_auth_policy_middleware not in app_ref.middlewares:
                app_ref.middlewares.append(gateway_auth_policy_middleware)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Gateway auth check not installed, so the gateway routes will not start: %s", e)

    _install_gateway_auth(app)

    def _register_third_party_access_routes(app_ref: web.Application) -> None:
        """Register loopback-only security controls for third-party agent access."""
        if not callable(_require_api_access) or not callable(_require_loopback) or not callable(_read_json):
            log.warning("Third-party access route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.third_party_agent_access_aiohttp import register_third_party_agent_access_routes

            register_third_party_agent_access_routes(
                app_ref,
                require_api_access=_require_api_access,
                require_loopback=_require_loopback,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Third-party access routes unavailable: %s", e)

    _register_third_party_access_routes(app)

    def _register_plugin_kernel_routes(app_ref: web.Application) -> None:
        """Register the loopback-only live plugin controls (unplug/replug/reload)."""
        if not callable(_require_api_access) or not callable(_require_loopback) or not callable(_read_json):
            log.warning("Live plugin route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.plugin_kernel_routes import register_plugin_kernel_routes

            register_plugin_kernel_routes(
                app_ref,
                require_api_access=_require_api_access,
                require_loopback=_require_loopback,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Live plugin routes unavailable: %s", e)

    _register_plugin_kernel_routes(app)

    def _register_preferences_routes(app_ref: web.Application) -> None:
        """Register the preferences API once runtime guards exist."""
        if not callable(_require_api_access):
            log.warning("Preferences/memory route registration skipped: missing runtime dependencies")
            return
        try:
            from thomas.server.routes.preferences_aiohttp import register_preferences_routes

            register_preferences_routes(
                app_ref,
                require_api_access=_require_api_access,
                read_json=_read_json,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Preferences/memory routes unavailable: %s", e)

    _register_preferences_routes(app)


def register_late_route_families(
    app: web.Application,
    config: AppConfig,
    *,
    web_dir: Any,
    require_api_access: Callable[..., Any],
    read_json: Callable[..., Any],
    require_loopback: Callable[..., Any],
    log: logging.Logger,
) -> None:
    """The families that followed the companion family: Thomas projects
    and OpenAI Codex. Mission and the
    chat-unavailable sentinel stay in the initializer because it calls them later, not
    in place."""
    _require_api_access = require_api_access
    _read_json = read_json
    _require_loopback = require_loopback

    def _register_self_project_routes(app_ref: web.Application) -> None:
        """Start a Thomas project without Chat, and list where each one stands (loopback only). Reading a stopped
        project's change is the project_change row's, not this one's."""
        if not callable(_require_loopback):
            log.warning("Thomas project routes skipped: missing the loopback guard")
            return
        try:
            from thomas.server.routes.self_project_routes import register_self_project_routes

            register_self_project_routes(app_ref, require_loopback=_require_loopback)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError, ValueError) as e:
            log.warning("Thomas project routes unavailable: %s", e)

    _register_self_project_routes(app)
