"""Gateway route package exports."""

from __future__ import annotations

from aiohttp import web

from . import p127_gateway_restart_command as p127
from . import p135_gateway_state_persistence_model as p135
from . import p136_gateway_auth_policy_enforcement as p136
from . import p137_gateway_logs_filter_command as p137
from . import p139_openai_compat_route_scaffold as p139
from . import p140_openai_chat_completions_non_stream as p140
from . import p141_openai_chat_completions_stream as p141
from . import p142_openai_tool_call_passthrough_mapping as p142
from . import p144_responses_compat_route_scaffold as p144
from . import p145_responses_create_non_stream as p145
from . import p146_responses_create_stream_events as p146
from . import p147_responses_tool_result_mapping as p147


def register_gateway_routes(app: web.Application, config: object | None = None) -> None:
    _ = config
    # p136 installs gateway_auth_policy_middleware. It was missing from this
    # tuple, so the middleware was never added to app.middlewares and
    # gateway_auth_mode was enforced on exactly ONE of the 27 live /gateway/*
    # routes -- /gateway/restart, which hand-rolls its own check by importing
    # p136 directly. Everything else answered regardless of the token: probed
    # with a deliberately wrong bearer token, GET /v1/gateway/state returned 200
    # with state, and POST /gateway/logs/filter reached its handler.
    #
    # Worse, the two endpoints an operator would use to confirm their config had
    # taken effect are p136's own, so they 404'd -- the misconfiguration could
    # not be detected from outside while the runbook
    # (docs/ops/GATEWAY_SECURITY_RUNBOOK.md) instructed operators to rely on it.
    #
    # Wiring it is inert until auth is switched on: authorize_gateway_request
    # returns allowed when `policy.required` is false, exempts OPTIONS so CORS
    # preflight cannot break, and under the default "auto" scope ignores any
    # path that is not a gateway target.
    for mod in (p127, p135, p136, p137, p139, p140, p141, p142, p144, p145, p146, p147):
        register = getattr(mod, "register", None)
        if callable(register):
            register(app)
            continue
        setup_routes = getattr(mod, "setup_routes", None)
        if callable(setup_routes):
            setup_routes(app)
            continue
        get_aiohttp_routes = getattr(mod, "get_aiohttp_routes", None)
        if callable(get_aiohttp_routes):
            app.add_routes(get_aiohttp_routes())
            continue
        routes = getattr(mod, "routes", None)
        if routes is not None:
            app.add_routes(routes)


__all__ = ["register_gateway_routes"]
