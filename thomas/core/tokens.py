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
from typing import Any, Dict, List, Optional

# Chars-per-token ratio. Conservative default that slightly overestimates
# token count (better to trim too early than blow the context window).
_CHARS_PER_TOKEN = float(os.environ.get("THOMAS_TOKEN_RATIO", "3.5"))


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length.

    This is intentionally conservative (overestimates slightly)
    to prevent context window overflow.
    """
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def estimate_message_tokens(message: Dict[str, Any]) -> int:
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


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """Estimate total tokens across a list of messages.

    Adds a base overhead of ~3 tokens for the messages wrapper.
    """
    if not messages:
        return 0
    return 3 + sum(estimate_message_tokens(m) for m in messages)


def estimate_tools_tokens(tools: List[Dict[str, Any]]) -> int:
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
    messages: List[Dict[str, Any]],
    budget: int,
    system_tokens: int = 0,
    tools_tokens: int = 0,
    preserve_first: int = 1,
    preserve_last: int = 4,
) -> List[Dict[str, Any]]:
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
    kept_middle: List[Dict[str, Any]] = []
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
