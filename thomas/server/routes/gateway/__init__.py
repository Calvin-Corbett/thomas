"""Gateway route package exports."""

from __future__ import annotations

from aiohttp import web

from . import p139_openai_compat_route_scaffold as p139
from . import p140_openai_chat_completions_non_stream as p140
from . import p141_openai_chat_completions_stream as p141
from . import p144_responses_compat_route_scaffold as p144
from . import p145_responses_create_non_stream as p145
from . import p146_responses_create_stream_events as p146


def register_gateway_routes(app: web.Application, config: object | None = None) -> None:
    _ = config
    for mod in (p139, p140, p141, p144, p145, p146):
        register = getattr(mod, "register", None)
        if callable(register):
            register(app)
            continue
        routes = getattr(mod, "routes", None)
        if routes is not None:
            app.add_routes(routes)


__all__ = ["register_gateway_routes"]
