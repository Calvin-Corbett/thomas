"""Isolated web and tool registration for a candidate plugin generation."""

from __future__ import annotations

import copy
from typing import Any

from aiohttp import web

from thomas.server.app_keys import APP_TOOLS
from thomas.server.live_routes import WebService


def stage_web(service: Any, owners: set[str]) -> WebService:
    """Copy registration tables, leaving the serving app and old tool loans intact."""
    shadow = web.Application()
    shadow._state.update(service.app._state)
    tools = service.app.get(APP_TOOLS)
    if tools is not None:
        shadow._state[APP_TOOLS] = copy.copy(tools)
        shadow[APP_TOOLS]._tools = dict(tools._tools)
        for name, tool in list(shadow[APP_TOOLS]._tools.items()):
            if getattr(getattr(tool, "lending", None), "owner", None) in owners:
                shadow[APP_TOOLS].unregister(name)
    return WebService(
        shadow,
        service.config,
        require_api_access=service.require_api_access,
        read_json=service.read_json,
        require_loopback=service.require_loopback,
        web_dir=service.web_dir,
    )
