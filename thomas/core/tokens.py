"""Token counting and estimation for context window management.

Provides fast token estimation without requiring tokenizer dependencies.
Uses a calibrated chars-per-token ratio that works well across models:
- GPT-4/Claude: ~3.5-4.0 chars per token
- Qwen/Llama:   ~3.2-3.8 chars per token
- We use 3.5 as a conservative middle ground

For precise counting with a specific model, set THOMAS_TOKEN_RATIO env var.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Sequence
from typing import Any

log = logging.getLogger(__name__)

# Chars-per-token ratio. Conservative default that slightly overestimates
# token count (better to trim too early than blow the context window).
_CHARS_PER_TOKEN = float(os.environ.get("THOMAS_TOKEN_RATIO", "3.5"))
_COMPACT_TOOL_ARGUMENT_CHARS = 1024

# The sentence every trim marker carries, and the count it opens with. The
# heuristic compactor writes the same sentence with a trailing clause, so the
# prefix is matched rather than the whole line.
_TRIM_MARKER_TEXT = "earlier messages trimmed to fit context window"
_TRIM_MARKER_COUNT = re.compile(r"\[(\d+) earlier messages trimmed")


def _trim_marker_count(message: dict[str, Any]) -> int:
    """How many earlier messages a trim marker already accounts for.

    0 when the message is not a trim marker.
    """
    content = message.get("content")
    if not isinstance(content, str) or _TRIM_MARKER_TEXT not in content:
        return 0
    match = _TRIM_MARKER_COUNT.search(content)
    return int(match.group(1)) if match else 0


class ContextBudgetExhausted(ValueError):
    """The request cannot hold tool results produced in the current run, and no summary covers them.

    Raised instead of sending a request without them, so the run stops rather than continuing blind.
    """


class RequiredRequestTooLarge(ValueError):
    """The message budget cannot fit the required instructions and latest request."""


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length.

    This is intentionally conservative (overestimates slightly)
    to prevent context window overflow.
    """
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate tokens in a single chat message.

    Accounts for message structure overhead (~4 tokens per message
    for role, delimiters, etc.)
    """
    overhead = 4  # role + structural tokens

    content = message.get("content", "")
    if isinstance(content, str):
        tokens = estimate_tokens(content) + overhead
    elif isinstance(content, list):
        # Anthropic-style content blocks
        tokens = overhead
        for block in content:
            if isinstance(block, dict):
                tokens += estimate_tokens(block.get("text", ""))
            elif isinstance(block, str):
                tokens += estimate_tokens(block)
    else:
        tokens = overhead

    # Tool calls add overhead
    tool_calls = message.get("tool_calls", [])
    for tc in tool_calls:
        func = tc.get("function", {})
        tokens += estimate_tokens(func.get("name", ""))
        tokens += estimate_tokens(func.get("arguments", ""))
        tokens += 3  # structural tokens per tool call

    return tokens


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens across a list of messages.

    Adds a base overhead of ~3 tokens for the messages wrapper.
    """
    if not messages:
        return 0
    return 3 + sum(estimate_message_tokens(m) for m in messages)


def estimate_tools_tokens(tools: list[dict[str, Any]]) -> int:
    """Estimate tokens consumed by tool specifications.

    Tool specs are sent with every request and consume significant context.
    Each tool is roughly: name + description + parameter schema.
    """
    if not tools:
        return 0
    total = 0
    for tool in tools:
        func = tool.get("function", {})
        total += estimate_tokens(func.get("name", ""))
        total += estimate_tokens(func.get("description", ""))
        params = func.get("parameters", {})
        total += estimate_tokens(json.dumps(params))
        total += 5  # structural overhead per tool
    return total


def trim_messages_to_budget(
    messages: list[dict[str, Any]],
    budget: int,
    system_tokens: int = 0,
    tools_tokens: int = 0,
    preserve_first: int = 1,
    preserve_last: int = 4,
    required: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Trim a message list to fit within a token budget.

    Strategy:
    - Always keep the first `preserve_first` messages (system prompt context)
    - Always keep the last `preserve_last` messages (recent conversation)
    - Drop middle messages oldest-first
    - Insert a "[conversation trimmed]" marker where messages were dropped
    - Keep a tool call and its results together, and never drop a required message

    Args:
        messages: Full message list (excluding system message)
        budget: Total token budget for the context window
        system_tokens: Tokens already consumed by system message
        tools_tokens: Tokens consumed by tool specifications
        preserve_first: Keep this many messages from the start
        preserve_last: Keep this many messages from the end
        required: Messages, by identity, that are never dropped (the active task and
            current steering)

    Returns:
        Trimmed message list that fits within budget
    """
    available = budget - system_tokens - tools_tokens - 100  # 100 token safety margin

    # If everything fits, return as-is
    total = estimate_messages_tokens(messages)
    if total <= available:
        return messages

    # Must trim. Protect head and tail.
    if len(messages) <= preserve_first + preserve_last:
        # Not enough messages to trim intelligently — just return all
        return messages

    required_ids = {id(message) for message in required or ()}
    spans = tool_group_spans(messages)

    # Head and tail are whole spans. A tool call and its results are one unit, so
    # neither boundary may fall between them; a tail boundary inside a group moves
    # back to the start of the group, keeping recent results with their call.
    head_end = 0
    for _start, end in spans:
        if end > preserve_first:
            break
        head_end = end
    tail_start = len(messages)
    for start, _end in reversed(spans):
        if len(messages) - tail_start >= preserve_last or start < head_end:
            break
        tail_start = start

    head = messages[:head_end]
    tail = messages[tail_start:]
    middle_spans = [(start, end) for start, end in spans if start >= head_end and end <= tail_start]
    required_spans = [
        (start, end)
        for start, end in middle_spans
        if any(id(messages[index]) in required_ids for index in range(start, end))
    ]

    # Calculate protected token cost
    head_tokens = estimate_messages_tokens(head)
    tail_tokens = estimate_messages_tokens(tail)

    if available - head_tokens - tail_tokens <= 0:
        # Even head and tail do not fit: keep the tail and every required message.
        kept_before_tail = [message for message in head if id(message) in required_ids]
        for start, end in required_spans:
            kept_before_tail.extend(messages[start:end])
        return kept_before_tail + tail

    def _span_tokens(span: tuple[int, int]) -> int:
        return sum(estimate_message_tokens(message) for message in messages[span[0] : span[1]])

    remaining_budget = available - head_tokens - tail_tokens - sum(_span_tokens(span) for span in required_spans)

    # Keep middle spans from the end (most recent) that fit; required spans always stay.
    kept: set[tuple[int, int]] = set(required_spans)
    used = 0
    # Iterate backwards (newest to oldest)
    for span in reversed(middle_spans):
        if span in kept:
            continue
        span_tokens = _span_tokens(span)
        if used + span_tokens > remaining_budget:
            break
        kept.add(span)
        used += span_tokens
    kept_middle = [message for span in middle_spans if span in kept for message in messages[span[0] : span[1]]]
    dropped_messages = [message for span in middle_spans if span not in kept for message in messages[span[0] : span[1]]]

    # A marker left by an EARLIER trim is not one lost message: it is the only
    # record of the N this list has already lost. `_build_messages` trims twice
    # (the route's soft history cap, then the model's window), and the second
    # pass treated the first pass's marker as ordinary middle content -- it
    # dropped it and announced "[2 earlier messages trimmed]" for a list that
    # had lost 23, deleting the sentence that said so. Same shape as the
    # compaction bug fixed in 1d8a26b8, one layer down. Absorbing the dropped
    # marker's count keeps the number true whatever order the stages run in.
    dropped = sum(_trim_marker_count(message) or 1 for message in dropped_messages)
    if dropped > 0:
        trim_marker = {
            "role": "system",
            "content": f"[{dropped} earlier messages trimmed to fit context window]",
        }
        return head + [trim_marker] + kept_middle + tail
    else:
        return head + kept_middle + tail


def _tool_call_ids(message: dict[str, Any]) -> set[str]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return set()
    return {str(call.get("id") or "") for call in calls if isinstance(call, dict) and call.get("id")}


def tool_group_spans(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Split messages into units that are kept or dropped whole.

    An assistant message with tool calls runs to the last result for those calls
    that arrives before the next assistant message, so it also holds anything
    stored between its results, such as a live user amendment. No shortening step
    can then leave a result whose call is gone. Every other message is its own unit.
    """
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(messages):
        end = index + 1
        call_ids = _tool_call_ids(messages[index]) if messages[index].get("role") == "assistant" else set()
        if call_ids:
            pending = set(call_ids)
            scan = index + 1
            while scan < len(messages) and pending:
                message = messages[scan]
                if message.get("role") == "assistant":
                    break
                if message.get("role") == "tool":
                    call_id = str(message.get("tool_call_id") or "")
                    if call_id not in call_ids:
                        break
                    pending.discard(call_id)
                    end = scan + 1
                scan += 1
        spans.append((index, end))
        index = end
    return spans


def _compact_tool_arguments(raw: Any) -> str:
    if isinstance(raw, str):
        text = raw or "{}"
    else:
        try:
            text = json.dumps(raw if raw is not None else {}, ensure_ascii=False)
        except (TypeError, ValueError):
            text = "{}"
    if len(text) <= _COMPACT_TOOL_ARGUMENT_CHARS:
        return text
    identity: dict[str, Any] = {}
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        for key in ("path", "file", "filename", "name", "operation"):
            value = parsed.get(key)
            if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 256:
                identity[key] = value
    identity["_thomas_context"] = "completed tool arguments compacted"
    identity["original_chars"] = len(text)
    return json.dumps(identity, ensure_ascii=False, separators=(",", ":"))


def _compact_completed_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed_ids = {
        str(message.get("tool_call_id") or "")
        for message in messages
        if message.get("role") == "tool" and message.get("tool_call_id")
    }
    result = list(messages)
    for index, message in enumerate(messages):
        calls = message.get("tool_calls")
        if message.get("role") != "assistant" or not isinstance(calls, list):
            continue
        changed = False
        compacted_calls: list[Any] = []
        for call in calls:
            if not isinstance(call, dict) or str(call.get("id") or "") not in completed_ids:
                compacted_calls.append(call)
                continue
            function = call.get("function")
            if not isinstance(function, dict):
                compacted_calls.append(call)
                continue
            arguments = _compact_tool_arguments(function.get("arguments"))
            if arguments == function.get("arguments"):
                compacted_calls.append(call)
                continue
            changed = True
            compacted_calls.append({**call, "function": {**function, "arguments": arguments}})
        if changed:
            result[index] = {**message, "tool_calls": compacted_calls}
    return result


def _drop_orphan_tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declared: set[str] = set()
    result: list[dict[str, Any]] = []
    for message in messages:
        declared.update(_tool_call_ids(message))
        if message.get("role") == "tool":
            call_id = str(message.get("tool_call_id") or "")
            if not call_id or call_id not in declared:
                continue
        result.append(message)
    return result


def fit_messages_to_hard_cap(
    messages: list[dict[str, Any]],
    *,
    hard_cap: int,
    anchor_source: list[dict[str, Any]] | None = None,
    required_anchors: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fit disposable history without altering required request context.

    Large completed tool arguments are first replaced with valid, compact JSON.
    Older turns are then removed atomically. The most recent user message, every
    system/developer instruction and every required anchor (the active task and
    current steering, passed by the caller) are retained byte-for-byte; a required
    anchor missing from the list is restored after the leading instructions. If
    those required messages cannot fit, fail instead of silently deleting policy
    or request text.
    """

    cap = int(hard_cap)
    if cap <= 0:
        required_tokens = estimate_messages_tokens(list(messages))
        raise RequiredRequestTooLarge(
            f"Request messages need {required_tokens} estimated tokens, exceeding the {cap}-token message budget"
        )

    compacted = _compact_completed_tool_calls(list(messages))
    fitted = _drop_orphan_tool_results(compacted)
    if len(compacted) != len(fitted):
        log.warning("Dropped %d tool result(s) whose tool call is not in the request", len(compacted) - len(fitted))
    sources = anchor_source if anchor_source is not None else messages
    anchor = next((dict(message) for message in reversed(sources) if message.get("role") == "user"), None)
    if anchor is not None and not any(message.get("role") == "user" for message in fitted):
        fitted.insert(1 if fitted else 0, anchor)

    required = [message for message in required_anchors or () if isinstance(message, dict)]

    def _same(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return left is right or (left.get("role") == right.get("role") and left.get("content") == right.get("content"))

    for order, message in enumerate(required):
        if any(_same(message, present) for present in fitted):
            continue
        # Restore in canonical order (the task, then amendments in order): after the unit holding
        # the nearest earlier anchor that is present, never inside a tool exchange; with none
        # present, after the leading instructions.
        earlier = [
            position
            for position, present in enumerate(fitted)
            if any(_same(present, anchor_message) for anchor_message in required[:order])
        ]
        if earlier:
            insert_at = next(stop for start, stop in tool_group_spans(fitted) if start <= earlier[-1] < stop)
        else:
            insert_at = 0
            while insert_at < len(fitted) and fitted[insert_at].get("role") in {"system", "developer"}:
                insert_at += 1
        fitted.insert(insert_at, message)

    def _protected(position: int, anchor_index: int) -> bool:
        message = fitted[position]
        if position == anchor_index or message.get("role") in {"system", "developer"}:
            return True
        return any(_same(required_message, message) for required_message in required)

    while estimate_messages_tokens(fitted) > cap and len(fitted) > 2:
        anchor_index = next(
            (index for index in range(len(fitted) - 1, -1, -1) if fitted[index].get("role") == "user"),
            -1,
        )
        spans = tool_group_spans(fitted)
        span_by_start = {start: (start, stop) for start, stop in spans}

        def _turn(start_index: int) -> tuple[int, int]:
            # A user turn runs to the next unit that opens with a user or instruction message. A user
            # amendment stored inside a tool exchange belongs to that exchange, not to a new turn.
            unit = span_by_start[start_index]
            if fitted[start_index].get("role") != "user":
                return unit
            stop = unit[1]
            while stop in span_by_start and fitted[stop].get("role") not in {"system", "user", "developer"}:
                stop = span_by_start[stop][1]
            return start_index, stop

        removable: tuple[int, int] | None = None
        index = next((start for start, _stop in spans if start >= 1), len(fitted))
        while index < len(fitted):
            turn = _turn(index)
            if not any(_protected(position, anchor_index) for position in range(*turn)):
                removable = turn
                break
            if fitted[turn[0]].get("role") == "user" and _protected(turn[0], anchor_index):
                # The turn opens with a protected request: its later work can still go, one whole unit at a time.
                inner = span_by_start[turn[0]][1]
                while inner < turn[1]:
                    unit = span_by_start[inner]
                    if not any(_protected(position, anchor_index) for position in range(*unit)):
                        removable = unit
                        break
                    inner = unit[1]
                if removable is not None:
                    break
            index = turn[1]
        if removable is None:
            break
        del fitted[removable[0] : removable[1]]
        fitted = _drop_orphan_tool_results(fitted)

    required_tokens = estimate_messages_tokens(fitted)
    if required_tokens > cap:
        raise RequiredRequestTooLarge(
            "Required system/developer instructions and latest user request need "
            f"{required_tokens} estimated tokens, exceeding the {cap}-token message budget"
        )
    return fitted
