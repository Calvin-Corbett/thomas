"""Three-layer memory coordinator.

CRITICAL FIX for Bug #3: memory retrieval only fired once (iteration 0).
Subsequent iterations got an empty string for memory context, making Thomas
forget his entire knowledge base mid-turn.

New behaviour: ``MemoryCoordinator.refresh()`` is called at **every**
iteration by the orchestrator.  Smart caching prevents redundant queries:

    - Working memory: always fresh (rebuilt from conversation state)
    - Episodic memory: refreshed every iteration (fast-changing)
    - Semantic memory: refreshed every 3 iterations (slow-changing domain knowledge)

Architecture inspired by A-Mem (2026) and Google DeepMind's delegation
framework (Feb 2026).
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from thomas.chat.conversation import ConversationManager

log = logging.getLogger(__name__)

_RECALL_PROMPT_RE = re.compile(
    r"\b(?:what\s+(?:was|did|were)|remind\s+me|recall|previously|earlier|"
    r"did\s+i\s+tell|did\s+you\s+remember|remembered|stored|code\s+phrase|"
    r"temporary\s+code|what\s+phrase)\b",
    re.I,
)

# ── memory context dataclass ─────────────────────────────────────


@dataclass
class MemoryContext:
    """All three memory layers for a single iteration.

    Attributes
    ----------
    working:
        Current task context — recent decisions, active goals, in-progress
        variables.  Built directly from conversation state.
    episodic:
        What happened in this conversation — summaries of past turns,
        decisions made, tool results.  Retrieved from memory engine.
    semantic:
        Domain knowledge from the knowledge graph, FTS, and sparse vectors.
        Facts, relationships, procedures.  Retrieved from memory engine.
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


# ── memory coordinator ───────────────────────────────────────────


class MemoryCoordinator:
    """Three-layer memory system wrapping Thomas's existing MemoryEngine.

    The coordinator does NOT replace the MemoryEngine — it adds a structured
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
        How often to refresh semantic memory (in iterations).  Domain
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
        policy: Any = None,
    ) -> None:
        self._memory = memory_engine
        self._session_id = session_id
        self._semantic_interval = semantic_refresh_interval
        policy_budget = int(getattr(policy, "context_budget", 0) or 0)
        self._context_budget = min(context_budget, policy_budget) if policy_budget > 0 else context_budget
        self._include_thread = bool(getattr(policy, "include_thread", True))
        self._include_global = bool(getattr(policy, "include_global", True))
        self._include_profile = bool(getattr(policy, "include_profile", True))
        self._pins_only = bool(getattr(policy, "pins_only", False))
        self._pins_policy_applied = not self._pins_only
        if self._pins_only and self._memory is not None:
            setter = getattr(self._memory, "set_thread_memory_policy", None)
            if callable(setter):
                try:
                    setter(
                        self._session_id,
                        include_thread=self._include_thread,
                        include_global=self._include_global,
                        include_profile=self._include_profile,
                        pins_only=True,
                        max_pack_tokens=self._context_budget,
                    )
                    self._pins_policy_applied = True
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    log.warning("Pins-only memory policy could not be applied: %s", exc)

        # Caches
        self._semantic_cache: str = ""
        self._semantic_last_iteration: int = -999
        self._episodic_cache: str = ""

        # Episode log (for capturing what happened this session)
        self._episodes: list[dict[str, Any]] = []

    @staticmethod
    def _memory_result_text(result: Any) -> str:
        """Normalize legacy memory and Memory Fabric v2 retrieval results."""
        if result is None:
            return ""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            for key in ("text", "pack_text", "content"):
                value = result.get(key)
                if value:
                    return str(value)
            if any(key in result for key in ("text", "pack_text", "content")):
                return ""
        if isinstance(result, (list, tuple)):
            return "\n".join(str(item) for item in result if item is not None)
        for attr in ("text", "pack_text", "content"):
            value = getattr(result, attr, None)
            if value:
                return str(value)
        if any(hasattr(result, attr) for attr in ("text", "pack_text", "content")):
            return ""
        return str(result)

    async def _retrieve_memory_text(
        self,
        *,
        query: str,
        thread_id: str | None,
        budget: int,
        mode: str,
    ) -> str:
        """Call the configured memory backend across supported API shapes."""
        if self._memory is None or not hasattr(self._memory, "retrieve"):
            return ""

        retrieve = self._memory.retrieve
        api_thread_id = thread_id if thread_id is not None else self._session_id
        attempts = (
            lambda: retrieve(query=query, thread=thread_id, budget=budget, mode=mode),
            lambda: retrieve(query=query, thread_id=api_thread_id, budget_tokens=budget, mode=mode),
            lambda: retrieve(query=query, thread_id=api_thread_id, budget_tokens=budget),
            lambda: retrieve(api_thread_id, query, budget),
        )
        last_type_error: TypeError | None = None
        for attempt in attempts:
            try:
                # The production memory fabric is synchronous and may spend time in
                # SQLite retrieval.  Running it on aiohttp's event-loop thread makes
                # unrelated routes (including health checks) wait behind that query.
                result = await asyncio.to_thread(attempt)
                if isawaitable(result):
                    result = await result
                return self._memory_result_text(result)
            except TypeError as exc:
                last_type_error = exc
                continue
        if last_type_error is not None:
            raise last_type_error
        return ""

    def _recent_thread_memory(self, *, limit: int = 8) -> str:
        """Fetch recent raw thread episodes as a recall fallback."""
        candidates = [
            self._memory,
            getattr(self._memory, "_fabric_v2", None),
            getattr(self._memory, "fabric", None),
        ]
        db = None
        for candidate in candidates:
            candidate_db = getattr(candidate, "db", None)
            if candidate_db is not None and hasattr(candidate_db, "execute"):
                db = candidate_db
                break
        if db is None:
            return ""

        try:
            rows = db.execute(
                """
                SELECT role, content
                FROM episodes
                WHERE thread_id=?
                ORDER BY ts_ms DESC, id DESC
                LIMIT ?
                """,
                (self._session_id, int(limit)),
            ).fetchall()
        # ``db`` is duck-typed above (anything with ``.execute``); in practice it is
        # memory.v2 SqliteDB, so a missing ``episodes`` table, a closed connection or
        # a locked file all arrive as sqlite3.Error. The three builtins cover a db
        # object that is NOT sqlite-backed: no ``.fetchall`` on the result
        # (AttributeError), a different execute() signature (TypeError), or a bad
        # bind value (ValueError). This is a recall *fallback* -- an unknown failure
        # mode should surface rather than silently degrade recall.
        except (sqlite3.Error, AttributeError, TypeError, ValueError) as exc:
            log.debug("Recent thread memory fallback failed: %s", exc)
            return ""

        if not rows:
            return ""

        lines = ["[Recent thread memory]"]
        for row in reversed(list(rows)):
            role = str(row["role"] if isinstance(row, dict) else row["role"] if hasattr(row, "keys") else row[0])
            content = str(
                row["content"] if isinstance(row, dict) else row["content"] if hasattr(row, "keys") else row[1]
            )
            content = " ".join(content.split())
            if content:
                lines.append(f"  [{role}] {content[:500]}")
        return "\n".join(lines) if len(lines) > 1 else ""

    # ── main refresh entry point ─────────────────────────────────

    async def refresh(
        self,
        prompt: str,
        conversation: ConversationManager,
        iteration: int,
    ) -> MemoryContext:
        """Refresh all memory layers for the current iteration.

        Called at **every** iteration (not just #0).  Uses smart caching
        to avoid redundant queries to the memory engine.

        Returns
        -------
        MemoryContext with all three layers populated.
        """
        start = time.monotonic()

        # Layer 1: Working memory (always fresh — built from conversation)
        working = self._build_working_memory(conversation)

        # Layer 2: Episodic memory (refresh every iteration)
        episodic = await self._refresh_episodic(prompt, conversation)

        # Layer 3: Semantic memory (refresh every N iterations)
        semantic = await self._refresh_semantic(prompt, iteration)

        # Budget enforcement — trim if total exceeds budget
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

    # ── layer builders ───────────────────────────────────────────

    def _build_working_memory(
        self,
        conversation: ConversationManager,
    ) -> str:
        """Build working memory from current conversation state.

        Working memory captures:
        - What the user is currently asking
        - Recent tool results
        - Active goals / in-progress decisions
        """
        parts: list[str] = []

        # Last user message = current task
        last_user = conversation.last_user_message()
        if last_user:
            parts.append(f"Current request: {last_user[:500]}")

        # Last assistant message = what we just said
        last_asst = conversation.last_assistant_message()
        if last_asst:
            parts.append(f"Last response: {last_asst[:300]}")

        # Recent episodes from this session
        if self._episodes:
            recent = self._episodes[-3:]  # last 3 episodes
            summaries = []
            for ep in recent:
                s = f"Turn {ep.get('turn', '?')}: {ep.get('summary', '')[:150]}"
                summaries.append(s)
            parts.append("Recent activity:\n" + "\n".join(summaries))

        return "\n\n".join(parts)

    async def _refresh_episodic(
        self,
        prompt: str,
        conversation: ConversationManager,
    ) -> str:
        """Retrieve episodic memory — what happened in this conversation.

        Uses the memory engine to search for relevant past interactions
        scoped to this session/thread.
        """
        if self._memory is None or (not self._include_thread and not self._pins_only) or not self._pins_policy_applied:
            return ""

        try:
            # Query memory engine scoped to this thread
            if hasattr(self._memory, "retrieve"):
                self._episodic_cache = await self._retrieve_memory_text(
                    query=prompt,
                    thread_id=self._session_id,
                    budget=self._context_budget // 3,
                    mode="fast",
                )
                if _RECALL_PROMPT_RE.search(str(prompt or "")):
                    recent_memory = self._recent_thread_memory()
                    if recent_memory and recent_memory not in self._episodic_cache:
                        self._episodic_cache = (
                            f"{self._episodic_cache.rstrip()}\n\n{recent_memory}"
                            if self._episodic_cache.strip()
                            else recent_memory
                        )
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
            return self._episodic_cache  # return stale cache on error

    async def _refresh_semantic(
        self,
        prompt: str,
        iteration: int,
    ) -> str:
        """Retrieve semantic memory — domain knowledge, facts, relationships.

        Only refreshes every ``_semantic_interval`` iterations because
        domain knowledge changes slowly.  Uses full memory engine with
        all signals (FTS + sparse vec + knowledge graph).
        """
        # The current backend cannot distinguish global from profile semantic
        # results.  Require both scopes instead of leaking one the user disabled.
        if self._memory is None or self._pins_only or not (self._include_global and self._include_profile):
            return ""

        # Check if we need to refresh
        if (iteration - self._semantic_last_iteration) < self._semantic_interval:
            return self._semantic_cache  # return cached

        try:
            if hasattr(self._memory, "retrieve"):
                self._semantic_cache = await self._retrieve_memory_text(
                    query=prompt,
                    thread_id=None,  # all threads — domain knowledge is global when supported
                    budget=self._context_budget // 2,
                    mode="thorough",
                )
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
            return self._semantic_cache  # return stale cache on error

    # ── budget enforcement ───────────────────────────────────────

    def _enforce_budget(self, ctx: MemoryContext) -> MemoryContext:
        """Trim memory layers if total exceeds budget."""
        total = ctx.total_tokens
        if total <= self._context_budget:
            return ctx

        # Trim proportionally, prioritising working > episodic > semantic
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

    # ── episode capture ──────────────────────────────────────────

    async def capture_episode(
        self,
        turn_number: int,
        user_message: str,
        assistant_response: str,
        thinking: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        specialist: str = "",
    ) -> None:
        """Record this turn as an episode for future retrieval.

        Called by the orchestrator after each completed turn.
        """
        episode = {
            "turn": turn_number,
            "timestamp": time.time(),
            "user": user_message[:500],
            "assistant": assistant_response[:500],
            "summary": f"User asked: {user_message[:100]}... → Assistant: {assistant_response[:100]}...",
            "specialist": specialist,
            "tool_count": len(tool_calls) if tool_calls else 0,
        }
        self._episodes.append(episode)

        # Also persist to memory engine if available
        if self._memory is not None:
            try:
                if hasattr(self._memory, "add"):
                    await self._memory.add(
                        content=f"Turn {turn_number}: {user_message[:300]} → {assistant_response[:300]}",
                        thread=self._session_id,
                        metadata={"turn": turn_number, "specialist": specialist},
                    )
                elif hasattr(self._memory, "add_event"):
                    metadata = {"turn": turn_number, "specialist": specialist}
                    self._memory.add_event(
                        self._session_id,
                        "user_message",
                        user_message[:1000],
                        metadata,
                    )
                    if assistant_response:
                        self._memory.add_event(
                            self._session_id,
                            "assistant_message",
                            assistant_response[:1000],
                            metadata,
                        )
                elif hasattr(self._memory, "store"):
                    self._memory.store(
                        text=f"Turn {turn_number}: {user_message[:300]} → {assistant_response[:300]}",
                        thread_id=self._session_id,
                    )
            except Exception as exc:
                log.warning("Failed to persist episode to memory engine: %s", exc)
