"""Compatibility shim for the chat route helpers. The V1 chat engine is gone; Chat V2 owns ``/api/chat``."""

from __future__ import annotations

from thomas.agent.loop import AgentLoop

from .chat_aiohttp_helpers import ChatRouteDeps, _resolve_app_value, _resolve_runtime_config

__all__ = [
    "AgentLoop",
    "ChatRouteDeps",
    "_resolve_app_value",
    "_resolve_runtime_config",
]
