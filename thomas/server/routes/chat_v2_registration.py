"""Registration plumbing for the unified Chat V2 route set."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.chat.session_store import SessionStore
from thomas.marketplace.orchestrator.registry import SpecialistRegistry
from thomas.marketplace.specialists.coding import CodingSpecialist
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist
from thomas.marketplace.specialists.research import ResearchSpecialist
from thomas.marketplace.specialists.synthesis import SynthesisSpecialist
from thomas.marketplace.specialists.tools import ToolSpecialist
from thomas.server.chat_budget_ledger import get_chat_budget_ledger
from thomas.server.routes.chat_v2_announcements import handle_announce_delegation
from thomas.server.routes.chat_v2_keys import (
    APP_ANNOUNCE_LOCKS,
    APP_CHAT_BUDGET_LEDGER,
    APP_SESSION_LLM_CACHE,
    APP_SESSION_STORE,
    APP_SPECIALIST_REGISTRY,
    APP_VOICE_BRIDGE,
)
from thomas.server.routes.chat_v2_request_support import handle_cancel_delegation, handle_session_delegations
from thomas.server.routes.chat_v2_session_routes import (
    guard_chat_v2_read,
    handle_mark_delegation_reported,
    handle_session_delete,
    handle_session_export,
    handle_session_get,
    handle_session_truncate,
    handle_specialists_list,
)
from thomas.server.routes.chat_v2_support import _cleanup_cached_session_llms
from thomas.server.routes.chat_v2_voice import (
    handle_chat_speak,
    handle_chat_transcribe,
    handle_chat_voice_status,
)
from thomas.tools.voice import VoiceBridge

log = logging.getLogger(__name__)


def register_chat_v2_route_set(
    app: web.Application,
    *,
    config: Any,
    llm: Any,
    tools: Any,
    chat_handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    chat_store_dir: Path | None,
    require_api_access: Callable[[web.Request], None],
) -> None:
    """Create Chat V2 state and register every endpoint behind its proper guard."""
    if not callable(require_api_access):
        raise TypeError("require_api_access must be callable")
    store_dir = chat_store_dir or Path(".thomas") / "sessions_v2"
    app[APP_SESSION_STORE] = SessionStore(store_dir)
    app[APP_CHAT_BUDGET_LEDGER] = get_chat_budget_ledger(store_dir.parent / "chat_budget.json")
    app[APP_SESSION_LLM_CACHE] = {}
    app[APP_ANNOUNCE_LOCKS] = {}
    app[APP_VOICE_BRIDGE] = VoiceBridge()
    app.on_cleanup.append(_cleanup_cached_session_llms)

    registry = SpecialistRegistry()
    for specialist_cls in (
        ReasoningSpecialist,
        CodingSpecialist,
        ResearchSpecialist,
        ToolSpecialist,
        SynthesisSpecialist,
    ):
        try:
            registry.register(specialist_cls(config=config, llm=llm, tools=tools))
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            log.warning("Failed to register specialist %s: %s", specialist_cls.__name__, exc)
    app[APP_SPECIALIST_REGISTRY] = registry

    app.router.add_post("/api/chat", chat_handler)
    app.router.add_post("/api/v2/chat", chat_handler)
    app.router.add_post("/api/v2/chat/transcribe", handle_chat_transcribe)
    app.router.add_post("/api/v2/chat/speak", handle_chat_speak)
    app.router.add_get("/api/v2/chat/voice/status", guard_chat_v2_read(handle_chat_voice_status, require_api_access))
    app.router.add_get("/api/v2/chat/session/{session_id}", guard_chat_v2_read(handle_session_get, require_api_access))
    app.router.add_get(
        "/api/v2/chat/session/{session_id}/export",
        guard_chat_v2_read(handle_session_export, require_api_access),
    )
    app.router.add_post(
        "/api/v2/chat/session/{session_id}/truncate",
        guard_chat_v2_read(handle_session_truncate, require_api_access),
    )
    app.router.add_get(
        "/api/v2/chat/session/{session_id}/delegations",
        guard_chat_v2_read(handle_session_delegations, require_api_access),
    )
    app.router.add_post(
        "/api/v2/chat/session/{session_id}/delegations/{execution_id}/cancel",
        handle_cancel_delegation,
    )
    app.router.add_post(
        "/api/v2/chat/session/{session_id}/delegations/{execution_id}/reported",
        handle_mark_delegation_reported,
    )
    app.router.add_post(
        "/api/v2/chat/session/{session_id}/delegations/{execution_id}/announce",
        handle_announce_delegation,
    )
    app.router.add_delete("/api/v2/chat/session/{session_id}", handle_session_delete)
    app.router.add_get("/api/v2/chat/specialists", guard_chat_v2_read(handle_specialists_list, require_api_access))
    log.info("Chat V2 routes registered (%d specialists available)", len(registry.specialist_ids))
