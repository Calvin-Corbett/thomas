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
import os
from typing import Any

# Chars-per-token ratio. Conservative default that slightly overestimates
# token count (better to trim too early than blow the context window).
_CHARS_PER_TOKEN = float(os.environ.get("THOMAS_TOKEN_RATIO", "3.5"))
_COMPACT_TOOL_ARGUMENT_CHARS = 1024


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
) -> list[dict[str, Any]]:
    """Trim a message list to fit within a token budget.

    Strategy:
    - Always keep the first `preserve_first` messages (system prompt context)
    - Always keep the last `preserve_last` messages (recent conversation)
    - Drop middle messages oldest-first
    - Insert a "[conversation trimmed]" marker where messages were dropped

    Args:
        messages: Full message list (excluding system message)
        budget: Total token budget for the context window
        system_tokens: Tokens already consumed by system message
        tools_tokens: Tokens consumed by tool specifications
        preserve_first: Keep this many messages from the start
        preserve_last: Keep this many messages from the end

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

    head = messages[:preserve_first]
    tail = messages[-preserve_last:]
    middle = messages[preserve_first:-preserve_last]

    # Calculate protected token cost
    head_tokens = estimate_messages_tokens(head)
    tail_tokens = estimate_messages_tokens(tail)
    remaining_budget = available - head_tokens - tail_tokens

    if remaining_budget <= 0:
        # Even head+tail don't fit — keep only tail
        return tail

    # Keep middle messages from the end (most recent) that fit
    kept_middle: list[dict[str, Any]] = []
    used = 0
    # Iterate backwards (newest to oldest)
    for msg in reversed(middle):
        msg_tokens = estimate_message_tokens(msg)
        if used + msg_tokens > remaining_budget:
            break
        kept_middle.insert(0, msg)
        used += msg_tokens

    dropped = len(middle) - len(kept_middle)
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


def _turn_span(messages: list[dict[str, Any]], start: int) -> tuple[int, int]:
    role = str(messages[start].get("role") or "")
    end = start + 1
    if role == "user":
        while end < len(messages) and messages[end].get("role") not in {"system", "user", "developer"}:
            end += 1
    elif role == "assistant":
        call_ids = _tool_call_ids(messages[start])
        while end < len(messages) and messages[end].get("role") == "tool":
            if str(messages[end].get("tool_call_id") or "") not in call_ids:
                break
            end += 1
    return start, end


def fit_messages_to_hard_cap(
    messages: list[dict[str, Any]],
    *,
    hard_cap: int,
    anchor_source: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fit disposable history without altering required request context.

    Large completed tool arguments are first replaced with valid, compact JSON.
    Older turns are then removed atomically. The most recent user message and
    every system/developer instruction are retained byte-for-byte. If those
    required messages cannot fit, fail instead of silently deleting policy or
    request text.
    """

    cap = int(hard_cap)
    if cap <= 0:
        raise ValueError(f"Model message budget must be positive; received {cap} estimated tokens")

    fitted = _drop_orphan_tool_results(_compact_completed_tool_calls(list(messages)))
    sources = anchor_source if anchor_source is not None else messages
    anchor = next((dict(message) for message in reversed(sources) if message.get("role") == "user"), None)
    if anchor is not None and not any(message.get("role") == "user" for message in fitted):
        fitted.insert(1 if fitted else 0, anchor)

    while estimate_messages_tokens(fitted) > cap and len(fitted) > 2:
        anchor_index = next(
            (index for index in range(len(fitted) - 1, -1, -1) if fitted[index].get("role") == "user"),
            -1,
        )
        removable: tuple[int, int] | None = None
        index = 1
        while index < len(fitted):
            span = _turn_span(fitted, index)
            required_instruction = fitted[span[0]].get("role") in {"system", "developer"}
            if not required_instruction and not (span[0] <= anchor_index < span[1]):
                removable = span
                break
            index = span[1]
        if removable is None and anchor_index >= 0:
            index = anchor_index + 1
            if index < len(fitted) and fitted[index].get("role") not in {"system", "developer"}:
                removable = _turn_span(fitted, index)
        if removable is None:
            break
        del fitted[removable[0] : removable[1]]
        fitted = _drop_orphan_tool_results(fitted)

    required_tokens = estimate_messages_tokens(fitted)
    if required_tokens > cap:
        raise ValueError(
            "Required system/developer instructions and latest user request need "
            f"{required_tokens} estimated tokens, exceeding the {cap}-token message budget"
        )
    return fitted
