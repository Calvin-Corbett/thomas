"""Context compaction and summarization for Thomas agent loop.

Inspired by Claude Code's automatic context management:
when the conversation grows too large, summarize older turns
to preserve token budget for fresh reasoning.

Strategies:
  - Drop tool output details while keeping tool names + ok/fail status
  - Summarize older assistant turns into bullet points
  - Preserve the most recent N turns fully
  - Keep system messages and user messages intact
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Rough token estimate: 1 token ≈ 4 characters
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Rough token estimate from character count."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_message_tokens(msg: dict[str, Any]) -> int:
    """Estimate token count for a single message."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return estimate_tokens(content) + 4  # role overhead
    if isinstance(content, list):
        total = 4
        for part in content:
            if isinstance(part, dict):
                text = part.get("text", "")
                if isinstance(text, str):
                    total += estimate_tokens(text)
        return total
    return 10


def estimate_conversation_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens across all messages."""
    return sum(estimate_message_tokens(m) for m in messages)


def _summarize_tool_result(content: str, max_chars: int = 200) -> str:
    """Shrink a tool result to a compact summary."""
    if len(content) <= max_chars:
        return content
    # Try to parse as JSON and extract key info
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            if "ok" in data:
                status = "ok" if data["ok"] else "failed"
                error = data.get("error", "")
                return f"[{status}] {error[:100]}" if error else f"[{status}]"
            # Return first few keys
            keys = list(data.keys())[:5]
            return f"{{keys: {keys}, ...({len(data)} entries)}}"
        if isinstance(data, list):
            return f"[list of {len(data)} items]"
    except (json.JSONDecodeError, TypeError):
        pass
    # Plain text: keep first and last parts
    half = max_chars // 2
    return content[:half] + f" ...(truncated {len(content)} chars)... " + content[-half:]


def _summarize_assistant_content(content: str, max_chars: int = 300) -> str:
    """Summarize an assistant message to key points."""
    if len(content) <= max_chars:
        return content
    lines = content.splitlines()
    # Keep first 3 lines and last 2 lines
    if len(lines) > 8:
        kept = lines[:3] + [f"  ...(skipped {len(lines) - 5} lines)..."] + lines[-2:]
        result = "\n".join(kept)
        if len(result) <= max_chars * 2:
            return result
    return content[:max_chars] + f" ...(truncated, was {len(content)} chars)"


def compact_conversation(
    messages: list[dict[str, Any]],
    *,
    target_tokens: int = 8000,
    preserve_recent: int = 6,
    preserve_system: bool = True,
) -> list[dict[str, Any]]:
    """Compact a conversation to fit within a target token budget.

    Strategy (from least aggressive to most):
    1. Truncate tool results in older messages
    2. Summarize older assistant messages
    3. Drop oldest non-system messages entirely

    Args:
        messages: Full conversation history
        target_tokens: Target token count to fit within
        preserve_recent: Number of most recent messages to keep fully intact
        preserve_system: Always keep system messages

    Returns:
        Compacted message list
    """
    if not messages:
        return messages

    current_tokens = estimate_conversation_tokens(messages)
    if current_tokens <= target_tokens:
        return messages  # Already within budget

    log.info(
        "Compacting conversation: %d tokens -> target %d (preserve_recent=%d)",
        current_tokens,
        target_tokens,
        preserve_recent,
    )

    # Split into preserved (recent) and compactable (older)
    result = list(messages)
    compactable_end = max(0, len(result) - preserve_recent)

    # --- Pass 1: Truncate tool results ---
    for i in range(compactable_end):
        msg = result[i]
        if msg.get("role") == "tool" or (msg.get("role") == "assistant" and isinstance(msg.get("tool_calls"), list)):
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 200:
                result[i] = {**msg, "content": _summarize_tool_result(content)}

    current_tokens = estimate_conversation_tokens(result)
    if current_tokens <= target_tokens:
        log.info("Compaction pass 1 (tool truncation) sufficient: %d tokens", current_tokens)
        return result

    # --- Pass 2: Summarize assistant messages ---
    for i in range(compactable_end):
        msg = result[i]
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 300:
                result[i] = {**msg, "content": _summarize_assistant_content(content)}

    current_tokens = estimate_conversation_tokens(result)
    if current_tokens <= target_tokens:
        log.info("Compaction pass 2 (summarization) sufficient: %d tokens", current_tokens)
        return result

    # --- Pass 3: Drop oldest non-system messages ---
    dropped = 0
    while current_tokens > target_tokens and compactable_end > 0:
        msg = result[0]
        if preserve_system and msg.get("role") == "system":
            # Move past system messages
            if len(result) > preserve_recent + 1:
                result.pop(1)
                compactable_end -= 1
            else:
                break
        else:
            result.pop(0)
            compactable_end -= 1
        dropped += 1
        current_tokens = estimate_conversation_tokens(result)

    if dropped > 0:
        log.info("Compaction pass 3: dropped %d messages, now %d tokens", dropped, current_tokens)
        # Insert a compaction marker so the agent knows context was trimmed
        marker = {
            "role": "system",
            "content": (
                f"[Context compacted: {dropped} older messages were summarized or removed "
                f"to maintain context budget. Recent conversation preserved.]"
            ),
        }
        # Insert after any leading system messages
        insert_idx = 0
        for idx, m in enumerate(result):
            if m.get("role") == "system":
                insert_idx = idx + 1
            else:
                break
        result.insert(insert_idx, marker)

    return result


def should_compact(
    messages: list[dict[str, Any]],
    budget: int = 12000,
    threshold: float = 0.85,
) -> bool:
    """Check if conversation should be compacted.

    Returns True when estimated tokens exceed threshold * budget.
    """
    current = estimate_conversation_tokens(messages)
    return current > int(budget * threshold)
