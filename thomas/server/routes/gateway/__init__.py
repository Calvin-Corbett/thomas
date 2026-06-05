"""Gateway route package exports."""

from __future__ import annotations

from aiohttp import web

from . import p127_gateway_restart_command as p127
from . import p135_gateway_state_persistence_model as p135
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
    for mod in (p127, p135, p137, p139, p140, p141, p142, p144, p145, p146, p147):
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
