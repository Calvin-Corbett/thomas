"""Three-layer memory coordinator.

CRITICAL FIX for Bug #3: memory retrieval only fired once (iteration 0).
Subsequent iterations got an empty string for memory context, making Thomas
forget his entire knowledge base mid-turn.

New behaviour: ``MemoryCoordinator.refresh()`` is called at **every**
iteration by the orchestrator. Smart caching prevents redundant queries:

    - Working memory: always fresh (rebuilt from conversation state)
    - Episodic memory: refreshed every iteration (fast-changing)
    - Semantic memory: refreshed every 3 iterations (slow-changing domain knowledge)

Architecture inspired by A-Mem (2026) and Google DeepMind's delegation
framework (Feb 2026).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from thomas.chat.conversation import ConversationManager

log = logging.getLogger(__name__)


@dataclass
class MemoryContext:
    """All three memory layers for a single iteration.

    Attributes
    ----------
    working:
        Current task context - recent decisions, active goals, in-progress
        variables. Built directly from conversation state.
    episodic:
        What happened in this conversation - summaries of past turns,
        decisions made, tool results. Retrieved from memory engine.
    semantic:
        Domain knowledge from the knowledge graph, FTS, and sparse vectors.
        Facts, relationships, procedures. Retrieved from memory engine.
    iteration:
        Which iteration this context was built for.
    retrieved_at:
        Timestamp of retrieval.
    """

    working: str = ""
    episodic: str = ""
    semantic: str = ""
    iteration: int = 0
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_system_injection(self) -> str:
        """Format all layers for LLM system prompt injection."""
        parts: list[str] = []
        if self.working:
            parts.append(f"## WORKING CONTEXT (current task)\n{self.working}")
        if self.episodic:
            parts.append(f"## CONVERSATION MEMORY\n{self.episodic}")
        if self.semantic:
            parts.append(f"## KNOWLEDGE BASE\n{self.semantic}")
        return "\n\n".join(parts) if parts else ""

    @property
    def total_tokens(self) -> int:
        """Rough token estimate across all layers."""
        total = len(self.working) + len(self.episodic) + len(self.semantic)
        return max(1, total // 4)

    @property
    def is_empty(self) -> bool:
        return not (self.working or self.episodic or self.semantic)


class MemoryCoordinator:
    """Three-layer memory system wrapping Thomas's existing MemoryEngine.

    The coordinator does NOT replace the MemoryEngine - it adds a structured
    layer on top that separates working, episodic, and semantic memory, and
    handles refresh scheduling across iterations.

    Parameters
    ----------
    memory_engine:
        Thomas's existing MemoryEngine instance (FTS5 + sparse vec + KG).
        Can be ``None`` for sessions without memory.
    session_id:
        Current session/thread identifier for scoped queries.
    semantic_refresh_interval:
        How often to refresh semantic memory (in iterations). Domain
        knowledge changes slowly, so refreshing every iteration is wasteful.
    context_budget:
        Maximum token budget across all three layers.
    """

    def __init__(
        self,
        memory_engine: Any,
        session_id: str,
        *,
        semantic_refresh_interval: int = 3,
        context_budget: int = 4_000,
    ) -> None:
        self._memory = memory_engine
        self._session_id = session_id
        self._semantic_interval = semantic_refresh_interval
        self._context_budget = context_budget

        self._semantic_cache: str = ""
        self._semantic_last_iteration: int = -999
        self._episodic_cache: str = ""
        self._episodes: list[dict[str, Any]] = []

    async def refresh(
        self,
        prompt: str,
        conversation: ConversationManager,
        iteration: int,
    ) -> MemoryContext:
        """Refresh all memory layers for the current iteration."""
        start = time.monotonic()

        working = self._build_working_memory(conversation)
        episodic = await self._refresh_episodic(prompt, conversation)
        semantic = await self._refresh_semantic(prompt, iteration)

        ctx = MemoryContext(
            working=working,
            episodic=episodic,
            semantic=semantic,
            iteration=iteration,
        )
        ctx = self._enforce_budget(ctx)

        elapsed = (time.monotonic() - start) * 1000
        log.debug(
            "Memory refresh iter=%d: working=%d episodic=%d semantic=%d (%.0fms)",
            iteration,
            len(working),
            len(episodic),
            len(semantic),
            elapsed,
        )
        return ctx

    def _build_working_memory(
        self,
        conversation: ConversationManager,
    ) -> str:
        """Build working memory from current conversation state."""
        parts: list[str] = []
        messages = conversation.get_messages_ref()

        last_user = conversation.last_user_message()
        if last_user:
            parts.append(f"Current request: {last_user[:500]}")

        last_asst = conversation.last_assistant_message()
        if last_asst:
            parts.append(f"Last response: {last_asst[:300]}")

        recent_user_requests: list[str] = []
        recent_user_chars = 0
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            excerpt = content[:220]
            recent_user_requests.append(excerpt)
            recent_user_chars += len(excerpt)
            if len(recent_user_requests) >= 10 or recent_user_chars >= 1_800:
                break
        if len(recent_user_requests) > 1:
            parts.append(
                "Recent user requests:\n"
                + "\n".join(f"- {entry}" for entry in reversed(recent_user_requests))
            )

        if self._episodes:
            recent = self._episodes[-3:]
            summaries = []
            for ep in recent:
                summary = f"Turn {ep.get('turn', '?')}: {ep.get('summary', '')[:150]}"
                summaries.append(summary)
            parts.append("Recent activity:\n" + "\n".join(summaries))

        return "\n\n".join(parts)

    async def _refresh_episodic(
        self,
        prompt: str,
        conversation: ConversationManager,
    ) -> str:
        """Retrieve episodic memory scoped to this session/thread."""
        _ = conversation
        if self._memory is None:
            return ""

        try:
            if hasattr(self._memory, "retrieve"):
                ctx = self._memory.retrieve(
                    query=prompt,
                    thread=self._session_id,
                    budget=self._context_budget // 3,
                    mode="fast",
                )
                self._episodic_cache = getattr(ctx, "text", str(ctx)) if ctx else ""
            elif hasattr(self._memory, "search"):
                results = self._memory.search(
                    query=prompt,
                    thread_id=self._session_id,
                    limit=10,
                )
                self._episodic_cache = "\n".join(str(r) for r in (results or []))
            return self._episodic_cache
        except Exception as exc:
            log.warning("Episodic memory refresh failed: %s", exc)
            return self._episodic_cache

    async def _refresh_semantic(
        self,
        prompt: str,
        iteration: int,
    ) -> str:
        """Retrieve semantic memory - domain knowledge, facts, relationships."""
        if self._memory is None:
            return ""

        if (iteration - self._semantic_last_iteration) < self._semantic_interval:
            return self._semantic_cache

        try:
            if hasattr(self._memory, "retrieve"):
                ctx = self._memory.retrieve(
                    query=prompt,
                    thread=None,
                    budget=self._context_budget // 2,
                    mode="thorough",
                )
                self._semantic_cache = getattr(ctx, "text", str(ctx)) if ctx else ""
            elif hasattr(self._memory, "search"):
                results = self._memory.search(
                    query=prompt,
                    thread_id=None,
                    limit=20,
                )
                self._semantic_cache = "\n".join(str(r) for r in (results or []))
            self._semantic_last_iteration = iteration
            return self._semantic_cache
        except Exception as exc:
            log.warning("Semantic memory refresh failed: %s", exc)
            return self._semantic_cache

    def _enforce_budget(self, ctx: MemoryContext) -> MemoryContext:
        """Trim memory layers if total exceeds budget."""
        total = ctx.total_tokens
        if total <= self._context_budget:
            return ctx

        ratio = self._context_budget / max(total, 1)
        working = ctx.working[: int(len(ctx.working) * min(1.0, ratio * 1.5))]
        episodic = ctx.episodic[: int(len(ctx.episodic) * ratio)]
        semantic = ctx.semantic[: int(len(ctx.semantic) * ratio * 0.8)]

        return MemoryContext(
            working=working,
            episodic=episodic,
            semantic=semantic,
            iteration=ctx.iteration,
        )

    async def capture_episode(
        self,
        turn_number: int,
        user_message: str,
        assistant_response: str,
        thinking: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        specialist: str = "",
    ) -> None:
        """Record this turn as an episode for future retrieval."""
        _ = thinking
        episode = {
            "turn": turn_number,
            "timestamp": time.time(),
            "user": user_message[:500],
            "assistant": assistant_response[:500],
            "summary": f"User asked: {user_message[:100]}... -> Assistant: {assistant_response[:100]}...",
            "specialist": specialist,
            "tool_count": len(tool_calls) if tool_calls else 0,
        }
        self._episodes.append(episode)

        if self._memory is None:
            return

        try:
            metadata = {"turn": turn_number, "specialist": specialist}
            add_event = getattr(self._memory, "add_event", None)
            if callable(add_event):
                # Persist each side of the turn separately so later recall can
                # match the original user wording instead of only a merged summary.
                await asyncio.to_thread(
                    add_event,
                    self._session_id,
                    "user_message",
                    user_message[:500],
                    metadata,
                )
                await asyncio.to_thread(
                    add_event,
                    self._session_id,
                    "assistant_response",
                    assistant_response[:500],
                    metadata,
                )
                return

            if hasattr(self._memory, "add"):
                await self._memory.add(
                    content=f"Turn {turn_number}: {user_message[:300]} -> {assistant_response[:300]}",
                    thread=self._session_id,
                    metadata=metadata,
                )
            elif hasattr(self._memory, "store"):
                self._memory.store(
                    text=f"Turn {turn_number}: {user_message[:300]} -> {assistant_response[:300]}",
                    thread_id=self._session_id,
                )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            log.warning("Failed to persist episode to memory engine: %s", exc)
