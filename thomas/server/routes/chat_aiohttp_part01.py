"""aiohttp route registration for the chat execution endpoint."""

from __future__ import annotations

import asyncio
import copy
import logging
import re
import secrets
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from thomas.agent.loop import AgentLoop
from thomas.core.autonomy import clamp_autonomy_level
from thomas.core.config import AppConfig, load_config
from thomas.models.chat_controls import resolve_ui_control_request
from thomas.server.app_keys import (
    APP_CONFIG,
    ChatSession,
)
from thomas.server.chat_control_mode import handle_ui_control_chat

log = logging.getLogger(__name__)
_DEFAULT_AGENT_LOOP = AgentLoop
_DEFAULT_RESOLVE_UI_CONTROL_REQUEST = resolve_ui_control_request
_DEFAULT_HANDLE_UI_CONTROL_CHAT = handle_ui_control_chat


# Per-session message queues for mid-run interruption.
# When a session has an active run, incoming messages are pushed here
# instead of being rejected. The AgentLoop checks this queue between
# tool completions and injects the message as a new user turn.
_SESSION_MSG_QUEUES: dict[str, asyncio.Queue[str | None]] = {}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"1", "true", "t", "yes", "y", "on", "enabled", "enable", "ok"}


def _clone_conversation_fallback(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clone_conversation_fallback(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clone_conversation_fallback(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_clone_conversation_fallback(v) for v in value)
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


def _create_parallel_fork_session(
    parent_sid: str,
    sessions: dict[str, Any],
) -> tuple[str, int]:
    base_session = sessions[parent_sid]
    fork_sid = f"{parent_sid}::parallel::{secrets.token_urlsafe(4)}"
    base_len = len(base_session.conversation) if isinstance(base_session, ChatSession) else 0
    try:
        cloned_conversation = copy.deepcopy(base_session.conversation)
    except Exception as exc:
        log.warning("Parallel fork: deepcopy failed for %s, using safe fallback clone: %s", parent_sid[:12], exc)
        cloned_conversation = _clone_conversation_fallback(
            base_session.conversation if isinstance(base_session, ChatSession) else []
        )
    sessions[fork_sid] = ChatSession(
        id=fork_sid,
        conversation=cloned_conversation,
        profile=str(getattr(base_session, "profile", "")),
        model_id=getattr(base_session, "model_id", None),
        autonomy_level=clamp_autonomy_level(getattr(base_session, "autonomy_level", 3), default=3),
    )
    return fork_sid, base_len


def _appkey_identity(key: Any) -> str:
    rep = repr(key)
    match = re.match(r"^<AppKey\(([^,]+),\s*type=.*\)>$", rep)
    if match:
        name = str(match.group(1) or "")
        marker = "thomas.server.app_keys."
        idx = name.find(marker)
        if idx >= 0:
            return name[idx:]
        return name
    return str(key)


def _resolve_app_value(
    app: web.Application,
    key: Any,
    *,
    expected_type: Any = None,
    default: Any = None,
    required: bool = False,
) -> Any:
    value = app.get(key)
    if expected_type is None:
        if value is not None:
            return value
    elif isinstance(value, expected_type):
        return value

    target_identity = _appkey_identity(key)
    for existing_key, existing_value in app.items():
        if _appkey_identity(existing_key) != target_identity:
            continue
        if expected_type is not None and not isinstance(existing_value, expected_type):
            continue
        app[key] = existing_value
        return existing_value

    if required:
        raise KeyError(key)
    return default


def _resolve_runtime_config(app: web.Application) -> AppConfig:
    """Return runtime AppConfig, tolerating AppKey identity drift after restarts."""
    cfg = _resolve_app_value(app, APP_CONFIG, expected_type=AppConfig)
    if isinstance(cfg, AppConfig):
        return cfg
    for value in app.values():
        if isinstance(value, AppConfig):
            app[APP_CONFIG] = value
            return value
    cfg = load_config()
    app[APP_CONFIG] = cfg
    return cfg


COMPANION_PHONE_SYSTEM_PROMPT = (
    "You are Thomas Infinite Companion, the purpose-built mobile control agent for Thomas. "
    "Your primary job is helping the user control Thomas from their phone and ship companion apps safely.\n"
    "Treat app creation, app-store publishing, and device-targeted app push as first-class flows. "
    "When the user asks for website-style experiences, prefer websocket-backed headless web modules "
    "that run inside companion app surfaces.\n"
    "Always include setup guidance when device pairing/app setup is missing. "
    "Keep responses concise and action-oriented by default. "
    "When a request implies an action, execute safely and report progress clearly. "
    "Ask only the minimum clarifying question required when intent is ambiguous."
)


# ---------------------------------------------------------------------------
# Dependency bundle
# ---------------------------------------------------------------------------
@dataclass
class ChatRouteDeps:
    """Dependency bundle for the chat route (closures from create_app)."""

    require_api_access: Any
    read_json: Any
    session_lock_for: Any
    begin_session_run: Any
    end_session_run: Any
    task_ledger_update: Any
    model_cfg_with_secrets: Any
    failover_cfgs_with_secrets: Any
    resolve_natural_model_switch: Any
    chat_file_for: Any
    read_chat_from_disk: Any
    save_chat_to_disk: Any
    build_tools: Any


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------
