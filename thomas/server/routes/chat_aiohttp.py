"""Compatibility shim for aiohttp chat route registration."""

from __future__ import annotations

from thomas.agent.loop import AgentLoop

from .chat_aiohttp_handlers import extract_missing_inputs, register_chat_routes
from .chat_aiohttp_helpers import ChatRouteDeps, _resolve_app_value, _resolve_runtime_config

__all__ = [
    "AgentLoop",
    "ChatRouteDeps",
    "_resolve_app_value",
    "_resolve_runtime_config",
    "extract_missing_inputs",
    "register_chat_routes",
]
