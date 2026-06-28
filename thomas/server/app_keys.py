"""Typed AppKey constants and shared data classes for the Thomas server.

Route modules import keys from here to access ``app[KEY]`` without
depending on the monolithic ``app.py`` module.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.autonomy import DEFAULT_AUTONOMY_LEVEL
from thomas.core.config import AppConfig
from thomas.server.secrets import SecretStore
from thomas.tools.registry import ToolRegistry

# App-level typed keys
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
APP_APPROVALS_BROKER = web.AppKey("approvals_broker", object)
APP_GUARDRAILS_CTX = web.AppKey("guardrails_ctx", dict)
APP_ENGINE_MANAGER = web.AppKey("engine_manager", object)
APP_TASK_LEDGER = web.AppKey("task_ledger", object)
APP_MUTATING_ROUTE_POLICY_SNAPSHOT = web.AppKey("mutating_route_policy_snapshot", dict)
APP_CHAT_AUTOPILOT_LAST_BY_GOAL = web.AppKey("chat_autopilot_last_by_goal", dict)
APP_CHAT_AUTOPILOT_LAST_BY_GOAL_LOCK = web.AppKey("chat_autopilot_last_by_goal_lock", asyncio.Lock)
APP_DIAGNOSTICS = web.AppKey("diagnostics", dict)
APP_BOOT_TIME = web.AppKey("boot_time", float)
APP_BOOT_DURATION = web.AppKey("boot_duration", float)
APP_CRASH_COUNT = web.AppKey("crash_count", int)
APP_SHUTDOWN_EVENT = web.AppKey("shutdown_event", asyncio.Event)
APP_RESTART_REQUESTED = web.AppKey("restart_requested", bool)
APP_RUNTIME_GUARD_STATE = web.AppKey("runtime_guard_state", dict)
APP_RUNTIME_GUARD_TASK = web.AppKey("runtime_guard_task", object)
APP_BOOT_DOCTOR_ROOT = web.AppKey("boot_doctor_root", Path)
APP_LOCAL_STEP_UP_AUTH_PROVIDER = web.AppKey("local_step_up_auth_provider", object)
APP_PROTECTED_INTERNALS_GATE = web.AppKey("protected_internals_gate", object)
APP_REQUIRE_API_ACCESS = web.AppKey("require_api_access", object)


@dataclass
class ChatSession:
    """In-memory representation of a chat session."""

    id: str
    conversation: list[dict[str, Any]]
    profile: str
    model_id: str | None = None
    autonomy_level: int = DEFAULT_AUTONOMY_LEVEL  # L2 Assist — ask before acting (Calvin law)
    system_prompt: str | None = None
    reasoning_effort: str | None = None
    session_token_spend: int = 0
    conversation_mode: str = "default"
    active_plan: dict[str, Any] | None = None
    task_definition_status: str = "idle"
    task_definition: dict[str, Any] | None = None
    task_evaluation: dict[str, Any] | None = None
    benchmark_session: dict[str, Any] | None = None
    last_user_message: str = ""
    last_assistant_message: str = ""
