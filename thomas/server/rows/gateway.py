"""The gateway routes, as a row: restart, state, log filter, the OpenAI-style and Responses-style endpoints, and the policy.

Off takes these 28 routes away, and that is all. The check of who may call stays installed by the server whether the row
is on or off, so with ``gateway_auth_scope = all`` a path of any kind is still refused without a token while this is
off, and every route here is refused without one while it is on. ``gateway_auth_policy_middleware`` is installed in
``thomas/server/app_routes_families.py`` and cannot be turned off, because aiohttp fixes its middleware list when the
server starts. If that install did not happen, this row refuses to start rather than answer with no check in front of it.

The chat-completion and Responses endpoints are not covered by the default scope of that check (``gateway_auth_scope``
unset or ``auto`` covers ``/gateway``, ``/ws`` and ``/v1/gateway`` only), and that is how they were before this row.
Gateway state lives in memory on the running app, so it survives off and on and is lost at a restart. Whatever session
the OpenAI-style proxy opened to its upstream is closed when the row stops.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Gateway:
    name = "gateway"
    inject = ("web",)
    imports = (
        "thomas.server.routes.gateway.p127_gateway_restart_command",
        "thomas.server.routes.gateway.p135_gateway_state_persistence_model",
        "thomas.server.routes.gateway.p137_gateway_logs_filter_command",
        "thomas.server.routes.gateway.p139_openai_compat_route_scaffold",
        "thomas.server.routes.gateway.p140_openai_chat_completions_non_stream",
        "thomas.server.routes.gateway.p141_openai_chat_completions_stream",
        "thomas.server.routes.gateway.p142_openai_tool_call_passthrough_mapping",
        "thomas.server.routes.gateway.p144_responses_compat_route_scaffold",
        "thomas.server.routes.gateway.p145_responses_create_non_stream",
        "thomas.server.routes.gateway.p146_responses_create_stream_events",
        "thomas.server.routes.gateway.p147_responses_tool_result_mapping",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.gateway import register_gateway_routes

        service = ctx["web"]
        register_gateway_routes(service.view(ctx), service.config)
        # After the routes, so a refusal throws them away with the row. Not a log and a return: that reads active.
        _require_the_check_of_who_may_call(service.app)


def _require_the_check_of_who_may_call(app: Any) -> None:
    from thomas.server.routes.gateway.p136_gateway_auth_policy_enforcement import gateway_auth_policy_middleware

    if gateway_auth_policy_middleware not in app.middlewares:
        raise RuntimeError("the gateway has no check of who may call installed, so its routes are not started")


plugin = _Gateway()
