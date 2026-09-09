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

from thomas.agent.context_compaction_heuristics import (
    _CHARS_PER_TOKEN,
    _COMPACTION_MARKER,
    _apply_heuristic_compaction,
    _extract_key_info_from_messages,
    _format_token_count,
    _is_compaction_summary,
    _summarize_assistant_content,
    _summarize_tool_result,
    estimate_conversation_tokens,
    estimate_message_tokens,
    estimate_tokens,
)
from thomas.core import capture_context
from thomas.core.capture_context import CAPTURE_EXCEPTIONS
from thomas.marketplace.observability.session_log_events import compaction_payload

log = logging.getLogger(__name__)

# estimate_tokens / estimate_message_tokens / estimate_conversation_tokens,
# _is_compaction_summary, _summarize_tool_result, _summarize_assistant_content,
# _extract_key_info_from_messages, _format_token_count, _apply_heuristic_compaction,
# _CHARS_PER_TOKEN and _COMPACTION_MARKER all live in context_compaction_heuristics.py
# now (M5, 2026-08-25 honesty-spine fix wave -- kept this file under the monolith
# guard's line budget). Imported above and re-exported under their original names
# so every existing caller (loop_core.py, repl_compact.py, repl_runtime.py, and the
# test suite, several of which import them directly from this module) needs no change.

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
        self.compaction_event_failures = 0  # honesty spine: counted, never fatal

    def _record_compaction_event(
        self, *, run_id: str | None, summary_text: str, replaced_from: int, replaced_to: int, by: str, spliced=None
    ) -> None:
        """Append one history/compaction event; never lets a capture failure break compact()."""
        if run_id is None:
            return
        try:
            s = spliced or {}
            role, content = s.get("role", "system"), str(s.get("content") or "compacted")
            recon = s.get("reconstruction", "exact")
            payload = compaction_payload(summary_text, replaced_from, replaced_to, by, role, content, recon)
            capture_context._append_capture_event(run_id, payload)  # Task 2's writer-aware seq source
        except CAPTURE_EXCEPTIONS as e:
            log.debug("Compaction: history/compaction append failed (%s): %s", type(e).__name__, e)
            self.compaction_event_failures += 1

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

        # Honesty spine: resolve the correlated run ONCE (current(), else ambient).
        try:
            event_run_id = capture_context.current() or capture_context.ambient_run_id()
        except CAPTURE_EXCEPTIONS:
            event_run_id = None

        # Try LLM-based summarization first, correlated to the SAME run its
        # own history/compaction event lands on. Each heuristic call below
        # gets its OWN inner try/finally (nested, not one outer wrap, to
        # keep the pre-existing except line un-re-indented -- a re-indent
        # reads as a brand-new handler to exception_handler_gate).
        compaction_source = "heuristic"
        _summary_capture_token = capture_context.set_capture_run(event_run_id) if event_run_id else None
        if use_llm and self._llm is not None:
            # KNOWN GAP: BaseException (asyncio cancellation) from the LLM await skips this except AND the token reset below - sticky-token risk remains on this path until the LLM dispatch is extracted to a helper wrapped in try/finally (deferred, task-3 re-review 2026-08-25).
            try:
                summaries = await self._summarize_segments_with_llm(segments)
                result.segments_summarized = len(summaries)
                compaction_source = "llm"
            except Exception as e:
                log.warning("LLM summarization failed, falling back to heuristic: %s", e)
                try:
                    summaries = self._summarize_segments_heuristic(segments)
                    result.segments_summarized = len(summaries)
                finally:
                    if _summary_capture_token is not None:
                        capture_context.reset(_summary_capture_token)
                        _summary_capture_token = None
        else:
            try:
                summaries = self._summarize_segments_heuristic(segments)
                result.segments_summarized = len(summaries)
            finally:
                if _summary_capture_token is not None:
                    capture_context.reset(_summary_capture_token)
                    _summary_capture_token = None
        if _summary_capture_token is not None:
            capture_context.reset(_summary_capture_token)

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
                self._record_compaction_event(
                    run_id=event_run_id,
                    # A segment can summarize to nothing -- compaction_payload rejects a blank summary_text.
                    summary_text=combined_summary.strip()
                    or f"{compactable_end - compactable_start} messages compacted (no summary text)",
                    replaced_from=compactable_start,
                    replaced_to=compactable_end,
                    by=compaction_source,
                    spliced=summary_msg,
                )
                return result

            # If still over budget, apply additional heuristic trimming
            messages[:] = new_messages

        # Fallback: progressive heuristic compaction if still over budget
        dropped = _apply_heuristic_compaction(messages, target_budget, preserve_recent)

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
        base = messages[compactable_start] if compactable_start < len(messages) else {}
        self._record_compaction_event(
            run_id=event_run_id,
            summary_text=result.summary_text.strip()
            or f"heuristic trim of {compactable_end - compactable_start} messages (no summary text)",
            replaced_from=compactable_start,
            replaced_to=compactable_end,
            by=compaction_source if result.summary_text.strip() else "heuristic-trim",
            # exact iff a real splice happened AND Pass 3 dropped nothing extra.
            spliced={**base, "reconstruction": "exact" if (summaries and not dropped) else "lossy-fallback"},
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


# --- Legacy API (backward compatibility) ---
# _format_token_count and _apply_heuristic_compaction now live in
# context_compaction_heuristics.py (imported above, M5 split).


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
