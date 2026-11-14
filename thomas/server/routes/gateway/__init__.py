"""Gateway route package exports.

Importing this package loads none of the modules below. ``register_gateway_routes`` imports each one as it registers it,
so a server that never registers the gateway never loads them, and the commands that import one module from here (the
``thomas gateway`` commands, and the server's own check of who may call) do not pay for the other eleven.

The check of who may call is not registered here. ``gateway_auth_policy_middleware`` is installed by the server itself,
in ``thomas/server/app_routes_families.py``, whether or not these routes are on, because ``gateway_auth_scope = all`` makes
it refuse every path on the server that has no token, and a middleware list cannot change once the server is running.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from aiohttp import web

# In the order they have always registered. From p136 only the two policy routes are added here.
_MODULES = (
    "p127_gateway_restart_command",
    "p135_gateway_state_persistence_model",
    "p136_gateway_auth_policy_enforcement",
    "p137_gateway_logs_filter_command",
    "p139_openai_compat_route_scaffold",
    "p140_openai_chat_completions_non_stream",
    "p141_openai_chat_completions_stream",
    "p142_openai_tool_call_passthrough_mapping",
    "p144_responses_compat_route_scaffold",
    "p145_responses_create_non_stream",
    "p146_responses_create_stream_events",
    "p147_responses_tool_result_mapping",
)
_POLICY_MODULE = "p136_gateway_auth_policy_enforcement"


def _add_routes_of(module: Any, app: Any) -> None:
    register = getattr(module, "register", None)
    if callable(register):
        register(app)
        return
    setup_routes = getattr(module, "setup_routes", None)
    if callable(setup_routes):
        setup_routes(app)
        return
    get_aiohttp_routes = getattr(module, "get_aiohttp_routes", None)
    if callable(get_aiohttp_routes):
        app.add_routes(get_aiohttp_routes())
        return
    routes = getattr(module, "routes", None)
    if routes is not None:
        app.add_routes(routes)


def register_gateway_routes(app: web.Application, config: object | None = None) -> None:
    """Add the gateway's routes to ``app``. It does not install the middleware that checks who is calling."""
    _ = config
    for name in _MODULES:
        module = import_module(f"{__name__}.{name}")
        if name == _POLICY_MODULE:
            # Its ``register`` would also append the middleware, and a view of the app has no middleware list to append to.
            module.add_routes(app)
            continue
        _add_routes_of(module, app)


__all__ = ["register_gateway_routes"]
