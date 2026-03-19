"""Context compaction and summarization for Thomas agent loop.

Inspired by Claude Code's automatic context management:
when the conversation grows too large, summarize older turns
to preserve token budget for fresh reasoning.

Strategies:
  - LLM-based summarization of older conversation segments
  - Drop tool output details while keeping tool names + ok/fail status
  - Summarize older assistant turns into bullet points
  - Preserve the most recent N turns fully
  - Keep system messages and user messages intact
  - Idempotent: compacted summaries are not re-compacted
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
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


_SUMMARIZATION_PROMPT = """\
Summarize the following conversation segment concisely. Preserve:
- File paths and directory names mentioned
- Key decisions made
- Error messages or error context
- Code structure discussed (function names, class names, module names)
- Tool results that affected decisions
- Any unresolved issues or next steps

Be concise but preserve actionable context. Use bullet points.
Do NOT include pleasantries or meta-commentary about the summarization.

Conversation segment:
{segment}

Summary:"""


@dataclass
class CompactionResult:
    """Result of a context compaction operation."""

    original_message_count: int = 0
    compacted_message_count: int = 0
    original_tokens: int = 0
    compacted_tokens: int = 0
    segments_summarized: int = 0
    summary_text: str = ""
    elapsed_ms: float = 0.0

    @property
    def tokens_saved(self) -> int:
        return max(0, self.original_tokens - self.compacted_tokens)

    @property
    def compression_ratio(self) -> float:
        if self.original_tokens == 0:
            return 1.0
        return self.compacted_tokens / self.original_tokens


class ContextCompactor:
    """Intelligent context compaction using LLM summarization.

    Compacts older conversation turns by generating concise summaries
    while preserving key technical context. Operates in-place on the
    conversation list to transparently extend conversation length.

    Usage:
        compactor = ContextCompactor(llm_client)
        result = await compactor.compact(
            conversation,
            target_budget=20000,
            preserve_recent=6,
        )
    """

    def __init__(
        self,
        llm: Any | None = None,
        *,
        max_summary_tokens: int = 500,
        segment_size: int = 8,
    ):
        """Initialize the compactor.

        Args:
            llm: LLMClient instance for generating summaries. If None,
                 falls back to local heuristic compaction (no LLM call).
            max_summary_tokens: Max tokens for each summary response.
            segment_size: Number of messages to summarize per segment.
        """
        self._llm = llm
        self._max_summary_tokens = max_summary_tokens
        self._segment_size = max(4, segment_size)

    async def compact(
        self,
        messages: list[dict[str, Any]],
        *,
        target_budget: int = 20000,
        preserve_recent: int = 6,
        use_llm: bool = True,
    ) -> CompactionResult:
        """Compact a conversation to fit within a target token budget.

        This method modifies the messages list in-place and also returns
        a CompactionResult with details about what was compacted.

        Args:
            messages: Conversation history (modified in-place).
            target_budget: Target token count for the conversation.
            preserve_recent: Number of most recent messages to preserve intact.
            use_llm: Whether to use LLM for intelligent summarization.
                     Falls back to heuristic compaction if False or no LLM.

        Returns:
            CompactionResult with metrics about the compaction.
        """
        t0 = time.monotonic()
        original_count = len(messages)
        original_tokens = estimate_conversation_tokens(messages)

        result = CompactionResult(
            original_message_count=original_count,
            original_tokens=original_tokens,
        )

        if original_tokens <= target_budget:
            result.compacted_message_count = original_count
            result.compacted_tokens = original_tokens
            result.elapsed_ms = (time.monotonic() - t0) * 1000
            return result

        log.info(
            "Starting context compaction: %d tokens -> target %d (%d messages, preserve_recent=%d)",
            original_tokens,
            target_budget,
            original_count,
            preserve_recent,
        )

        # Identify compactable vs preserved regions
        # Never compact: system messages at start, most recent N messages,
        # and already-compacted summary messages
        preserve_recent = max(4, preserve_recent)

        # Find the boundary between compactable and preserved
        compactable_end = max(0, len(messages) - preserve_recent)

        # Separate system messages from the beginning
        system_prefix_end = 0
        for i, msg in enumerate(messages):
            if msg.get("role") == "system":
                system_prefix_end = i + 1
            else:
                break

        # The compactable range is from system_prefix_end to compactable_end
        if compactable_end <= system_prefix_end:
            # Nothing to compact
            result.compacted_message_count = len(messages)
            result.compacted_tokens = estimate_conversation_tokens(messages)
            result.elapsed_ms = (time.monotonic() - t0) * 1000
            return result

        # Skip already-compacted summaries in the compactable range
        compactable_start = system_prefix_end
        for i in range(system_prefix_end, compactable_end):
            if _is_compaction_summary(messages[i]):
                compactable_start = i + 1
            else:
                break

        if compactable_start >= compactable_end:
            # Everything in the compactable range is already a summary
            result.compacted_message_count = len(messages)
            result.compacted_tokens = estimate_conversation_tokens(messages)
            result.elapsed_ms = (time.monotonic() - t0) * 1000
            return result

        compactable = messages[compactable_start:compactable_end]

        # Group compactable messages into segments, keeping tool call/result
        # pairs together to avoid orphaning
        segments = self._segment_messages(compactable)

        # Try LLM-based summarization first
        if use_llm and self._llm is not None:
            try:
                summaries = await self._summarize_segments_with_llm(segments)
                result.segments_summarized = len(summaries)
            except Exception as e:
                log.warning("LLM summarization failed, falling back to heuristic: %s", e)
                summaries = self._summarize_segments_heuristic(segments)
                result.segments_summarized = len(summaries)
        else:
            summaries = self._summarize_segments_heuristic(segments)
            result.segments_summarized = len(summaries)

        # Build the compacted summary message
        if summaries:
            combined_summary = "\n\n".join(summaries)
            result.summary_text = combined_summary

            summary_msg = {
                "role": "assistant",
                "content": (
                    f"{_COMPACTION_MARKER}\n"
                    f"Earlier conversation summary ({len(compactable)} messages compacted):\n\n"
                    f"{combined_summary}"
                ),
            }

            # Replace compactable messages with the summary
            new_messages = messages[:compactable_start] + [summary_msg] + messages[compactable_end:]

            # Check if we're within budget now
            new_tokens = estimate_conversation_tokens(new_messages)
            if new_tokens <= target_budget:
                messages[:] = new_messages
                result.compacted_message_count = len(messages)
                result.compacted_tokens = new_tokens
                result.elapsed_ms = (time.monotonic() - t0) * 1000
                log.info(
                    "Context compaction complete: %d -> %d tokens (%d -> %d messages)",
                    original_tokens,
                    new_tokens,
                    original_count,
                    len(messages),
                )
                return result

            # If still over budget, apply additional heuristic trimming
            messages[:] = new_messages

        # Fallback: progressive heuristic compaction if still over budget
        _apply_heuristic_compaction(messages, target_budget, preserve_recent)

        result.compacted_message_count = len(messages)
        result.compacted_tokens = estimate_conversation_tokens(messages)
        result.elapsed_ms = (time.monotonic() - t0) * 1000

        log.info(
            "Context compaction complete: %d -> %d tokens (%d -> %d messages, %.0fms)",
            original_tokens,
            result.compacted_tokens,
            original_count,
            result.compacted_message_count,
            result.elapsed_ms,
        )
        return result

    def _segment_messages(self, messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Group messages into segments for summarization.

        Keeps tool call/result pairs together to avoid orphaning.
        """
        segments: list[list[dict[str, Any]]] = []
        current_segment: list[dict[str, Any]] = []

        for msg in messages:
            current_segment.append(msg)

            # Check if this completes a natural boundary
            role = msg.get("role", "")
            is_tool_result = role == "tool"
            has_tool_calls = bool(msg.get("tool_calls"))

            # Don't split in the middle of a tool call -> tool result pair
            if has_tool_calls:
                continue  # Wait for the tool results

            if is_tool_result:
                # Check if more tool results are expected (next msg might also be tool)
                continue

            # Natural break point: end of user message or assistant message
            # without tool calls, or we've hit segment size
            if len(current_segment) >= self._segment_size and role != "tool":
                segments.append(current_segment)
                current_segment = []

        if current_segment:
            segments.append(current_segment)

        return segments

    async def _summarize_segments_with_llm(self, segments: list[list[dict[str, Any]]]) -> list[str]:
        """Use the LLM to generate summaries for each segment."""
        summaries: list[str] = []

        for segment in segments:
            segment_text = _extract_key_info_from_messages(segment)
            if not segment_text.strip():
                continue

            prompt = _SUMMARIZATION_PROMPT.format(segment=segment_text)

            try:
                response = await self._llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a conversation summarizer. "
                                "Produce concise, technical bullet-point summaries. "
                                "Preserve file paths, function names, error details, and decisions."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    tools=None,
                )
                summary = response.get("text", "").strip()
                if summary:
                    summaries.append(summary)
                else:
                    # Fallback to heuristic for this segment
                    summaries.append(self._heuristic_segment_summary(segment))
            except Exception as e:
                log.debug("LLM summary failed for segment: %s", e)
                summaries.append(self._heuristic_segment_summary(segment))

        return summaries

    def _summarize_segments_heuristic(self, segments: list[list[dict[str, Any]]]) -> list[str]:
        """Heuristic (non-LLM) summarization of message segments."""
        summaries: list[str] = []
        for segment in segments:
            summary = self._heuristic_segment_summary(segment)
            if summary:
                summaries.append(summary)
        return summaries

    @staticmethod
    def _heuristic_segment_summary(segment: list[dict[str, Any]]) -> str:
        """Create a heuristic summary of a message segment."""
        points: list[str] = []
        tool_names: list[str] = []
        file_paths: set[str] = set()

        import re

        path_pattern = re.compile(r'(?:[A-Za-z]:\\[^\s"\'<>|]+|/[^\s"\'<>|]{3,})')

        for msg in segment:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = str(content)

            # Extract file paths
            for match in path_pattern.finditer(content):
                fp = match.group(0).rstrip(".,;:)")
                if len(fp) > 5:
                    file_paths.add(fp)

            if role == "user":
                text = content.strip()
                if len(text) > 200:
                    text = text[:200] + "..."
                points.append(f"- User asked: {text}")

            elif role == "assistant":
                tc = msg.get("tool_calls", [])
                if isinstance(tc, list) and tc:
                    for call in tc:
                        if isinstance(call, dict):
                            func = call.get("function", {})
                            if isinstance(func, dict):
                                tool_names.append(func.get("name", "?"))
                text = content.strip()
                if text:
                    if len(text) > 200:
                        text = text[:200] + "..."
                    points.append(f"- Assistant: {text}")

            elif role == "tool":
                name = msg.get("name", msg.get("tool_name", "?"))
                text = content.strip()
                # Detect success/failure
                ok_hint = ""
                try:
                    data = json.loads(text)
                    if isinstance(data, dict) and "ok" in data:
                        ok_hint = " [ok]" if data["ok"] else " [failed]"
                except (json.JSONDecodeError, TypeError):
                    if "error" in text.lower()[:100]:
                        ok_hint = " [error]"
                points.append(f"- Tool {name}{ok_hint}: {_summarize_tool_result(text, 100)}")

        parts: list[str] = []
        if tool_names:
            unique_tools = list(dict.fromkeys(tool_names))
            parts.append(f"Tools used: {', '.join(unique_tools)}")
        if file_paths:
            sorted_paths = sorted(file_paths)[:10]
            parts.append(f"Files referenced: {', '.join(sorted_paths)}")
        if points:
            parts.extend(points[:15])  # Cap at 15 bullet points per segment

        return "\n".join(parts)

    def token_usage_info(self, messages: list[dict[str, Any]], context_window: int | None = None) -> dict[str, Any]:
        """Return current token usage information for display.

        Args:
            messages: Current conversation messages.
            context_window: Total context window size.
                If not provided or non-positive, context-limited decisions are
                disabled.

        Returns:
            Dict with usage metrics for UI display.
        """
        current_tokens = estimate_conversation_tokens(messages)
        context_window_int = int(context_window or 0)
        usage_ratio = current_tokens / max(1, context_window_int) if context_window_int > 0 else 0.0
        usage_pct = 0
        if context_window_int > 0:
            usage_pct = int(usage_ratio * 100)
            if current_tokens > 0 and usage_ratio > 0 and usage_pct == 0:
                usage_pct = 1
        return {
            "current_tokens": current_tokens,
            "context_window": context_window_int,
            "usage_ratio": usage_ratio,
            "usage_pct": usage_pct,
            "message_count": len(messages),
            "should_compact": usage_ratio > 0.75 if context_window_int > 0 else False,
            "display": _format_token_count(current_tokens),
            "display_budget": _format_token_count(context_window_int),
        }


def _format_token_count(tokens: int) -> str:
    """Format token count for display (e.g., 12.3k)."""
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return str(tokens)


def _apply_heuristic_compaction(
    messages: list[dict[str, Any]],
    target_tokens: int,
    preserve_recent: int,
) -> None:
    """Apply heuristic compaction directly on the message list (in-place).

    Progressive strategy:
    1. Truncate tool results in older messages
    2. Summarize older assistant messages
    3. Drop oldest non-system messages
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
        return

    # Pass 2: Summarize assistant messages
    for i in range(compactable_end):
        msg = messages[i]
        if msg.get("role") == "assistant" and not _is_compaction_summary(msg):
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 300:
                messages[i] = {**msg, "content": _summarize_assistant_content(content)}

    current_tokens = estimate_conversation_tokens(messages)
    if current_tokens <= target_tokens:
        return

    # Pass 3: Drop oldest non-system, non-summary messages
    dropped = 0
    while current_tokens > target_tokens and compactable_end > 0:
        msg = messages[0]
        if msg.get("role") == "system" or _is_compaction_summary(msg):
            if len(messages) > preserve_recent + 1:
                messages.pop(1)
                compactable_end -= 1
            else:
                break
        else:
            messages.pop(0)
            compactable_end -= 1
        dropped += 1
        current_tokens = estimate_conversation_tokens(messages)

    if dropped > 0:
        log.info("Heuristic compaction: dropped %d messages, now %d tokens", dropped, current_tokens)
        marker = {
            "role": "system",
            "content": (
                f"[{dropped} earlier messages trimmed to fit context window. " f"Recent conversation preserved.]"
            ),
        }
        insert_idx = 0
        for idx, m in enumerate(messages):
            if m.get("role") == "system" or _is_compaction_summary(m):
                insert_idx = idx + 1
            else:
                break
        messages.insert(insert_idx, marker)


# --- Legacy API (backward compatibility) ---


def compact_conversation(
    messages: list[dict[str, Any]],
    *,
    target_tokens: int = 8000,
    preserve_recent: int = 6,
    preserve_system: bool = True,
) -> list[dict[str, Any]]:
    """Compact a conversation to fit within a target token budget.

    This is the legacy synchronous API. For the full async API with LLM
    summarization, use ContextCompactor.compact() instead.

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
        return messages

    log.info(
        "Compacting conversation: %d tokens -> target %d (preserve_recent=%d)",
        current_tokens,
        target_tokens,
        preserve_recent,
    )

    result = list(messages)
    _apply_heuristic_compaction(result, target_tokens, preserve_recent)
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
