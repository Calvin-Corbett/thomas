"""Typed aiohttp application keys shared by Chat V2 route modules."""

from __future__ import annotations

from aiohttp import web

from thomas.chat.session_store import SessionStore
from thomas.marketplace.orchestrator.registry import SpecialistRegistry
from thomas.server.chat_budget_ledger import ChatBudgetLedger
from thomas.tools.voice import VoiceBridge

APP_SESSION_STORE = web.AppKey("chat_v2_session_store", SessionStore)
APP_SPECIALIST_REGISTRY = web.AppKey("chat_v2_specialist_registry", SpecialistRegistry)
APP_SESSION_LLM_CACHE = web.AppKey("chat_v2_session_llm_cache", dict)
APP_ANNOUNCE_LOCKS = web.AppKey("chat_v2_announce_locks", dict)
APP_VOICE_BRIDGE = web.AppKey("chat_v2_voice_bridge", VoiceBridge)
APP_CHAT_BUDGET_LEDGER = web.AppKey("chat_v2_budget_ledger", ChatBudgetLedger)

__all__ = [
    "APP_ANNOUNCE_LOCKS",
    "APP_CHAT_BUDGET_LEDGER",
    "APP_SESSION_LLM_CACHE",
    "APP_SESSION_STORE",
    "APP_SPECIALIST_REGISTRY",
    "APP_VOICE_BRIDGE",
]
