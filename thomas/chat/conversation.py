"""Copy-on-write ConversationManager.

CRITICAL FIX for Bug #1: context loss after compaction.

Old behaviour: ``self._conversation = compacted`` in loop.py:1157 broke the
shared list reference with ``session.conversation``.  New messages after
compaction were appended to the agent's private list while the session kept
the stale, uncompacted version.

New behaviour: ConversationManager is **immutable**.  Every mutation
(``append_message``, ``compact``) returns a *new* instance.  The orchestrator
explicitly passes the updated manager back to the SessionStore, so there is
never a dangling reference.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from collections.abc import Sequence
from typing import Any

log = logging.getLogger(__name__)

# ── token estimation ────────────────────────────────────────────────
_CHARS_PER_TOKEN = 4  # conservative estimate (GPT-family ≈ 3.5–4)


def _estimate_tokens(text: str) -> int:
    """Rough token count from character length."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _message_tokens(msg: dict[str, Any]) -> int:
    """Estimate token footprint of a single message dict."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return _estimate_tokens(content) + 4  # role/name overhead
    if isinstance(content, list):
        total = 4
        for part in content:
            if isinstance(part, dict):
                txt = part.get("text", "")
                if isinstance(txt, str):
                    total += _estimate_tokens(txt)
        return total
    return 10  # fallback for opaque content


# ── conversation manager ────────────────────────────────────────────


class ConversationManager:
    """Immutable, copy-on-write conversation history.

    Every mutation returns a **new** ConversationManager; ``self`` is never
    changed.  This eliminates the class of bugs caused by shared-mutable-list
    references between ``ChatSession`` and ``AgentLoop``.

    Parameters
    ----------
    messages:
        Initial message list.  A **deep copy** is made on construction so the
        caller can safely mutate their original list without affecting us.
    version:
        Monotonic version counter used for optimistic-locking / dirty checks.
    """

    __slots__ = ("_messages", "_version", "_token_cache")

    def __init__(
        self,
        messages: list[dict[str, Any]] | None = None,
        *,
        version: int = 0,
    ) -> None:
        self._messages: list[dict[str, Any]] = copy.deepcopy(messages) if messages else []
        self._version: int = version
        self._token_cache: int | None = None

    # ── read-only accessors ──────────────────────────────────────

    @property
    def version(self) -> int:
        """Monotonically increasing version (bumped on every mutation)."""
        return self._version

    @property
    def length(self) -> int:
        return len(self._messages)

    def get_messages(self) -> list[dict[str, Any]]:
        """Return a **deep copy** of the message list."""
        return copy.deepcopy(self._messages)

    def get_messages_ref(self) -> list[dict[str, Any]]:
        """Return a *shallow* read-only reference (for building LLM prompts).

        Callers **must not** mutate the returned list or its dicts.
        """
        return list(self._messages)

    def total_tokens(self) -> int:
        """Estimated total token count across all messages."""
        if self._token_cache is None:
            self._token_cache = sum(_message_tokens(m) for m in self._messages)
        return self._token_cache

    def last_n(self, n: int) -> list[dict[str, Any]]:
        """Return the last *n* messages (deep copy)."""
        return copy.deepcopy(self._messages[-n:]) if n else []

    def last_user_message(self) -> str | None:
        """Content of the most recent user message, or ``None``."""
        for m in reversed(self._messages):
            if m.get("role") == "user":
                c = m.get("content", "")
                return c if isinstance(c, str) else str(c)
        return None

    def last_assistant_message(self) -> str | None:
        """Content of the most recent assistant message, or ``None``."""
        for m in reversed(self._messages):
            if m.get("role") == "assistant":
                c = m.get("content", "")
                return c if isinstance(c, str) else str(c)
        return None

    # ── mutations (all return NEW instances) ─────────────────────

    def append_message(
        self,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationManager:
        """Return a new manager with one message appended.

        This **never** mutates ``self``.
        """
        msg: dict[str, Any] = {"role": role, "content": content}
        if metadata:
            msg["metadata"] = metadata
        new_msgs = copy.deepcopy(self._messages)
        new_msgs.append(msg)
        return ConversationManager(new_msgs, version=self._version + 1)

    def append_messages(
        self,
        messages: Sequence[dict[str, Any]],
    ) -> ConversationManager:
        """Batch-append multiple messages. Returns new instance."""
        if not messages:
            return self
        new_msgs = copy.deepcopy(self._messages)
        new_msgs.extend(copy.deepcopy(list(messages)))
        return ConversationManager(new_msgs, version=self._version + 1)

    def compact(
        self,
        target_tokens: int = 8_000,
        preserve_recent: int = 8,
        preserve_system: bool = True,
    ) -> ConversationManager:
        """Return a new manager with compacted history.

        Three-pass strategy (least → most aggressive):

        1. **Truncate tool results** in older messages (keep first 200 chars).
        2. **Summarize assistant messages** in older messages (keep first 300 chars).
        3. **Drop oldest** non-system messages until under ``target_tokens``.

        A ``[context compacted]`` marker is injected when messages are dropped.
        """
        msgs = copy.deepcopy(self._messages)
        total = sum(_message_tokens(m) for m in msgs)

        if total <= target_tokens:
            return ConversationManager(msgs, version=self._version + 1)

        # Determine compactable range (skip system + last `preserve_recent`)
        safe_end = max(0, len(msgs) - preserve_recent)

        # Pass 1 — truncate tool results
        for i in range(safe_end):
            m = msgs[i]
            content = m.get("content", "")
            if m.get("role") == "tool" or (
                isinstance(content, str)
                and len(content) > 800
                and m.get("role") == "assistant"
                and "tool_call" in str(m.get("metadata", ""))
            ):
                if isinstance(content, str) and len(content) > 200:
                    m["content"] = content[:200] + "\n...[truncated]"

        total = sum(_message_tokens(m) for m in msgs)
        if total <= target_tokens:
            return ConversationManager(msgs, version=self._version + 1)

        # Pass 2 — summarize assistant messages
        for i in range(safe_end):
            m = msgs[i]
            if m.get("role") == "assistant":
                content = m.get("content", "")
                if isinstance(content, str) and len(content) > 300:
                    lines = content.split("\n")
                    if len(lines) > 5:
                        summary = "\n".join(lines[:3]) + "\n...\n" + "\n".join(lines[-2:])
                        m["content"] = summary

        total = sum(_message_tokens(m) for m in msgs)
        if total <= target_tokens:
            return ConversationManager(msgs, version=self._version + 1)

        # Pass 3 — drop oldest non-system messages
        compacted: list[dict[str, Any]] = []
        dropped = 0
        for i, m in enumerate(msgs):
            if preserve_system and m.get("role") == "system" or i >= safe_end:
                compacted.append(m)
            else:
                dropped += 1

        if dropped:
            # Insert compaction marker after system messages
            insert_idx = 0
            for j, m in enumerate(compacted):
                if m.get("role") == "system":
                    insert_idx = j + 1
                else:
                    break
            compacted.insert(
                insert_idx,
                {
                    "role": "system",
                    "content": f"[Context compacted: {dropped} older messages summarized to save tokens]",
                },
            )

        return ConversationManager(compacted, version=self._version + 1)

    def get_context_window(
        self,
        max_tokens: int = 28_000,
        preserve_first: int = 1,
        preserve_last: int = 6,
    ) -> list[dict[str, Any]]:
        """Build a token-budgeted message list for LLM calls.

        Keeps the first ``preserve_first`` messages (usually system prompt)
        and the last ``preserve_last`` messages, trimming the middle if
        needed to stay under ``max_tokens``.
        """
        msgs = list(self._messages)
        total = sum(_message_tokens(m) for m in msgs)

        if total <= max_tokens:
            return copy.deepcopy(msgs)

        # Keep first N + last M, drop middle
        head = msgs[:preserve_first]
        tail = msgs[-preserve_last:] if preserve_last else []
        middle = msgs[preserve_first : len(msgs) - preserve_last if preserve_last else len(msgs)]

        # Drop middle messages from oldest until budget met
        kept_middle: list[dict[str, Any]] = []
        budget_used = sum(_message_tokens(m) for m in head) + sum(_message_tokens(m) for m in tail)

        for m in reversed(middle):
            cost = _message_tokens(m)
            if budget_used + cost <= max_tokens:
                kept_middle.insert(0, m)
                budget_used += cost

        # Say what was dropped. Pass 1 of the compactor above already writes
        # "...[truncated]" when it shortens a single tool result, but removing whole
        # turns from the middle left no trace at all -- so a constraint set twenty
        # messages ago could disappear and the model had no way to know it was
        # working from a conversation with a hole in it. Seamless amnesia is worse
        # than visible amnesia: it cannot be asked about.
        #
        # The marker is prepended to the first surviving message rather than added
        # as its own entry, because inserting a message mid-list breaks the
        # user/assistant alternation some providers require.
        dropped = len(middle) - len(kept_middle)
        if dropped > 0:
            plural = "s" if dropped != 1 else ""
            marker = f"[{dropped} earlier message{plural} omitted here to fit the context window.]\n\n"
            if kept_middle:
                first = dict(kept_middle[0])
                first["content"] = marker + str(first.get("content") or "")
                kept_middle = [first, *kept_middle[1:]]
            elif tail:
                first = dict(tail[0])
                first["content"] = marker + str(first.get("content") or "")
                tail = [first, *tail[1:]]

        result = head + kept_middle + tail
        return copy.deepcopy(result)

    # ── serialization ────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize for disk persistence."""
        return {
            "version": self._version,
            "messages": copy.deepcopy(self._messages),
            "total_tokens": self.total_tokens(),
            "message_count": len(self._messages),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationManager:
        """Deserialize from disk."""
        return cls(
            messages=data.get("messages", []),
            version=data.get("version", 0),
        )

    def fingerprint(self) -> str:
        """SHA-256 of serialized messages (for dirty-checking)."""
        raw = json.dumps(self._messages, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── dunder ───────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._messages)

    def __repr__(self) -> str:
        return (
            f"ConversationManager(messages={len(self._messages)}, "
            f"version={self._version}, "
            f"tokens≈{self.total_tokens()})"
        )
