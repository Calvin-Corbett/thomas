"""Thomas Chat Suite v2 — Brain/Orchestrator architecture.

Replaces the fragmented chat_aiohttp / chat_modes / chat_stream_events
pipeline with a clean, unified system where Thomas acts as a pure
orchestrator that delegates all work to specialist sub-agents.

Key modules:
    conversation    – Copy-on-write ConversationManager (fixes context loss)
    session_store   – Auto-persisting SessionStore (fixes crash data loss)
    memory_layers   – 3-layer MemoryCoordinator (fixes one-shot memory)
    thinking        – ThinkingTracker for reasoning display
    event_stream    – Unified NDJSON EventDispatcher
"""

from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.memory_layers import MemoryContext, MemoryCoordinator
from thomas.chat.session_store import SessionStore
from thomas.chat.thinking import ThinkingBlock, ThinkingTracker

__all__ = [
    "ConversationManager",
    "SessionStore",
    "MemoryCoordinator",
    "MemoryContext",
    "ThinkingTracker",
    "ThinkingBlock",
    "EventDispatcher",
]
