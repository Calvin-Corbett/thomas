"""Typed AppKey constants and shared data classes for the Thomas server.

Route modules import keys from here to access ``app[KEY]`` without
depending on the monolithic ``app.py`` module.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from aiohttp import web

from thomas.core.config import AppConfig
from thomas.server.secrets import SecretStore
from thomas.tools.registry import ToolRegistry

# ── App-level typed keys ──────────────────────────────────────────────

APP_CONFIG = web.AppKey("config", AppConfig)
APP_TOOLS = web.AppKey("tools", ToolRegistry)
APP_MEMORY = web.AppKey("memory", object)
APP_SECRETS = web.AppKey("secrets", SecretStore)
APP_SESSIONS = web.AppKey("sessions", dict)
APP_SESSION_LOCKS = web.AppKey("session_locks", dict)
APP_SESSION_LOCKS_LOCK = web.AppKey("session_locks_lock", asyncio.Lock)
APP_SESSION_ACTIVE_RUNS = web.AppKey("session_active_runs", set)
APP_SESSION_ACTIVE_RUNS_LOCK = web.AppKey("session_active_runs_lock", asyncio.Lock)
APP_RUN_STORE_ENABLED = web.AppKey("run_store_enabled", bool)
APP_RUN_STORE_MODULE = web.AppKey("run_store_module", object)
APP_ACTION_AUDIT = web.AppKey("action_audit", object)
APP_GUARDRAILS_ENABLED = web.AppKey("guardrails_enabled", bool)
APP_GUARDED_TOOL_RUNNER = web.AppKey("guarded_tool_runner", object)
APP_GUARDRAILS_CTX = web.AppKey("guardrails_ctx", dict)
APP_CODEX_BRIDGE = web.AppKey("_codex_bridge", object)
APP_ENGINE_MANAGER = web.AppKey("engine_manager", object)
APP_TASK_LEDGER = web.AppKey("task_ledger", object)
APP_MUTATING_ROUTE_POLICY_SNAPSHOT = web.AppKey("mutating_route_policy_snapshot", dict)


# ── Shared data classes ───────────────────────────────────────────────

@dataclass
class ChatSession:
    """In-memory representation of a chat session."""
    id: str
    conversation: List[Dict[str, Any]]
    profile: str
    model_id: Optional[str] = None
    autonomy_level: int = 3
    system_prompt: Optional[str] = None
    reasoning_effort: Optional[str] = None
    session_token_spend: int = 0
