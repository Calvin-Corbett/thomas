"""Where one request's tokens went, in the words the context panel shows.

The agent loop already estimates the size of the request it is about to send. This splits that number: the system
prompt, the tool definitions, what you said, what Thomas said, and the output of each tool he used. It is an estimate
(the same one the loop trims by), so the parts add up to the loop's own total.
"""

from __future__ import annotations

from typing import Any

from thomas.core.tokens import estimate_message_tokens

MAX_ROWS = 8


def _tool_name(call: Any) -> str:
    if not isinstance(call, dict):
        return ""
    function = call.get("function")
    return str((function.get("name") if isinstance(function, dict) else None) or call.get("name") or "")


def context_breakdown(messages: list[dict[str, Any]], token_estimate: int = 0) -> list[dict[str, Any]]:
    """Rows of ``{"label", "tokens"}``, largest first, at most ``MAX_ROWS`` with the rest folded into one row."""
    parts = {"System prompt": 0, "Your messages": 0, "Thomas's replies": 0}
    results: dict[str, int] = {}
    names: dict[str, str] = {}
    seen = 0
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        tokens = max(0, int(estimate_message_tokens(message)))
        seen += tokens
        role = message.get("role")
        if role == "system":
            parts["System prompt"] += tokens
        elif role == "user":
            parts["Your messages"] += tokens
        elif role == "assistant":
            parts["Thomas's replies"] += tokens
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict) and call.get("id"):
                    names[str(call["id"])] = _tool_name(call)
        elif role == "tool":
            name = names.get(str(message.get("tool_call_id") or "")) or str(message.get("name") or "") or "a tool"
            results[name] = results.get(name, 0) + tokens
    rows = [{"label": label, "tokens": tokens} for label, tokens in parts.items()]
    rows += [{"label": f"Results of {name}", "tokens": tokens} for name, tokens in results.items()]
    # What the request carries besides messages: the definitions of every tool Thomas may call.
    definitions = max(0, int(token_estimate or 0) - seen)
    if definitions:
        rows.append({"label": "Tool definitions", "tokens": definitions})
    rows = [row for row in rows if row["tokens"] > 0]
    rows.sort(key=lambda row: row["tokens"], reverse=True)
    if len(rows) > MAX_ROWS:
        rest = sum(row["tokens"] for row in rows[MAX_ROWS - 1 :])
        rows = rows[: MAX_ROWS - 1] + [{"label": "Everything else", "tokens": rest}]
    return rows
