"""Heuristic (non-LLM) helpers for context compaction.

Split out of `thomas/agent/context_compaction.py` to keep that file under the
monolith guard's line budget (M5, 2026-08-25 honesty-spine fix wave) -- this
is a coherent, self-contained unit (token estimation + the idempotency
marker + the three-pass local-heuristic trim), not a `*_part*.py` split.
Imported with a normal module import; `context_compaction.py` re-exports
these names under their original spots so no external caller needs to
change (loop_core.py / repl_compact.py / repl_runtime.py / the test suite
all still import them from `thomas.agent.context_compaction`).

This module has no dependency on `context_compaction.py` -- the import
direction is one-way (context_compaction imports from here) so there is no
circular-import risk.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Rough token estimate: 1 token ~ 4 characters
_CHARS_PER_TOKEN = 4

# Marker used to identify already-compacted summary messages
_COMPACTION_MARKER = "[context-summary]"


def estimate_tokens(text: str) -> int:
    """Rough token estimate from character count."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_message_tokens(msg: dict[str, Any]) -> int:
    """Estimate token count for a single message."""
    content = msg.get("content", "")
    if isinstance(content, str):
        tokens = estimate_tokens(content) + 4  # role overhead
    elif isinstance(content, list):
        tokens = 4
        for part in content:
            if isinstance(part, dict):
                text = part.get("text", "")
                if isinstance(text, str):
                    tokens += estimate_tokens(text)
            elif isinstance(part, str):
                tokens += estimate_tokens(part)
    else:
        tokens = 10

    # Tool calls add overhead
    tool_calls = msg.get("tool_calls", [])
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            func = tc.get("function", {})
            if isinstance(func, dict):
                tokens += estimate_tokens(func.get("name", ""))
                tokens += estimate_tokens(func.get("arguments", ""))
                tokens += 3
    return tokens


def estimate_conversation_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens across all messages."""
    return sum(estimate_message_tokens(m) for m in messages)


def _is_compaction_summary(msg: dict[str, Any]) -> bool:
    """Check if a message is already a compaction summary (idempotency guard)."""
    content = msg.get("content", "")
    if isinstance(content, str) and _COMPACTION_MARKER in content:
        return True
    return False


def _summarize_tool_result(content: str, max_chars: int = 200) -> str:
    """Shrink a tool result to a compact summary."""
    if len(content) <= max_chars:
        return content
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            if "ok" in data:
                status = "ok" if data["ok"] else "failed"
                error = data.get("error", "")
                return f"[{status}] {error[:100]}" if error else f"[{status}]"
            keys = list(data.keys())[:5]
            return f"{{keys: {keys}, ...({len(data)} entries)}}"
        if isinstance(data, list):
            return f"[list of {len(data)} items]"
    except (json.JSONDecodeError, TypeError):
        pass
    half = max_chars // 2
    return content[:half] + f" ...(truncated {len(content)} chars)... " + content[-half:]


def _summarize_assistant_content(content: str, max_chars: int = 300) -> str:
    """Summarize an assistant message to key points."""
    if len(content) <= max_chars:
        return content
    lines = content.splitlines()
    if len(lines) > 8:
        kept = lines[:3] + [f"  ...(skipped {len(lines) - 5} lines)..."] + lines[-2:]
        result = "\n".join(kept)
        if len(result) <= max_chars * 2:
            return result
    return content[:max_chars] + f" ...(truncated, was {len(content)} chars)"


def _extract_key_info_from_messages(messages: list[dict[str, Any]]) -> str:
    """Extract key information from a segment of messages for summarization prompt."""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)

        if role == "user":
            # Keep user messages concise
            text = content.strip()
            if len(text) > 500:
                text = text[:500] + "..."
            parts.append(f"USER: {text}")

        elif role == "assistant":
            text = content.strip()
            if len(text) > 800:
                text = text[:800] + "..."
            tool_calls = msg.get("tool_calls", [])
            if isinstance(tool_calls, list) and tool_calls:
                tool_names = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        func = tc.get("function", {})
                        if isinstance(func, dict):
                            tool_names.append(func.get("name", "?"))
                parts.append(f"ASSISTANT (tools: {', '.join(tool_names)}): {text}")
            else:
                parts.append(f"ASSISTANT: {text}")

        elif role == "tool":
            name = msg.get("name", msg.get("tool_name", "?"))
            text = content.strip()
            if len(text) > 300:
                text = text[:300] + "..."
            parts.append(f"TOOL[{name}]: {text}")

        elif role == "system" and not _is_compaction_summary(msg):
            text = content.strip()
            if len(text) > 200:
                text = text[:200] + "..."
            parts.append(f"SYSTEM: {text}")

    return "\n".join(parts)


def _format_token_count(tokens: int) -> str:
    """Format token count for display (e.g., 12.3k)."""
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return str(tokens)


def _apply_heuristic_compaction(
    messages: list[dict[str, Any]],
    target_tokens: int,
    preserve_recent: int,
) -> int:
    """Apply heuristic compaction directly on the message list (in-place).

    Progressive strategy:
    1. Truncate tool results in older messages
    2. Summarize older assistant messages
    3. Drop oldest non-system messages

    Returns the count Pass 3 dropped -- nonzero means messages in the range
    were removed outright, not replaced 1:1 (the caller's splice signal).
    """
    compactable_end = max(0, len(messages) - preserve_recent)

    # Pass 1: Truncate tool results
    for i in range(compactable_end):
        msg = messages[i]
        if msg.get("role") == "tool" or (msg.get("role") == "assistant" and isinstance(msg.get("tool_calls"), list)):
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 200:
                messages[i] = {**msg, "content": _summarize_tool_result(content)}

    current_tokens = estimate_conversation_tokens(messages)
    if current_tokens <= target_tokens:
        return 0

    # Pass 2: Summarize assistant messages
    for i in range(compactable_end):
        msg = messages[i]
        if msg.get("role") == "assistant" and not _is_compaction_summary(msg):
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 300:
                messages[i] = {**msg, "content": _summarize_assistant_content(content)}

    current_tokens = estimate_conversation_tokens(messages)
    if current_tokens <= target_tokens:
        return 0

    # Pass 3: Drop oldest non-system, non-summary messages
    #
    # This used to inspect messages[0] and then pop messages[1] without looking at
    # what index 1 was. A real conversation is [system prompt, [context-summary],
    # ...turns], so index 1 is the compaction summary -- the one artifact carrying
    # the turns already compacted away. It was the first thing deleted, every time,
    # and the marker below then reported it as one of "N earlier messages".
    #
    # Losing it is worse than losing the turns it replaced: a constraint agreed
    # thirty messages ago lived only there. So the oldest DROPPABLE message is found
    # by looking, which is what the heading above always said this did.
    dropped = 0
    while current_tokens > target_tokens and compactable_end > 0:
        drop_at = next(
            (
                i
                for i in range(compactable_end)
                if messages[i].get("role") != "system" and not _is_compaction_summary(messages[i])
            ),
            None,
        )
        if drop_at is None:
            # Everything still compactable is protected; shedding more would cost
            # the system prompt or the summary, which is never the cheaper trade.
            break
        messages.pop(drop_at)
        compactable_end -= 1
        dropped += 1
        current_tokens = estimate_conversation_tokens(messages)

    if dropped > 0:
        log.info("Heuristic compaction: dropped %d messages, now %d tokens", dropped, current_tokens)
        marker = {
            "role": "system",
            "content": (f"[{dropped} earlier messages trimmed to fit context window. Recent conversation preserved.]"),
        }
        insert_idx = 0
        for idx, m in enumerate(messages):
            if m.get("role") == "system" or _is_compaction_summary(m):
                insert_idx = idx + 1
            else:
                break
        messages.insert(insert_idx, marker)
    return dropped
