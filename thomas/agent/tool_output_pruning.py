"""Shrink stale tool outputs to a stub, deterministically, before compaction.

TB-4.0 run 3 (2026-09-04) sent about 116k prompt tokens per call for 128
iterations and never compacted: auto-compaction waits for 75% of the model's
window and then pays a model call to summarise. Frontier harnesses do the
cheap thing first: a tool output the model has already acted on is replaced
by its first lines plus a note saying how much was cut and how to get it
back. The recent turns stay verbatim; nothing here calls a model.
"""

from __future__ import annotations

from typing import Any

PRUNED_MARKER = "[pruned"


def _text_of(content: Any) -> str | None:
    return content if isinstance(content, str) else None


def prune_stale_tool_outputs(
    conversation: list[dict[str, Any]],
    *,
    keep_recent_messages: int = 12,
    min_chars: int = 2000,
    keep_head_chars: int = 400,
) -> int:
    """Replace large, old tool outputs in place. Returns the number of characters removed.

    A message is old when it sits before the last ``keep_recent_messages``
    messages. Only ``role == "tool"`` string contents longer than ``min_chars``
    are touched; user and assistant text, tool_call ids and names all stay.
    """
    if not isinstance(conversation, list) or keep_recent_messages < 0:
        return 0
    cutoff = max(0, len(conversation) - keep_recent_messages)
    removed = 0
    for message in conversation[:cutoff]:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        text = _text_of(message.get("content"))
        if text is None or len(text) <= min_chars or PRUNED_MARKER in text[-200:]:
            continue
        name = str(message.get("name") or message.get("tool_name") or "the tool")
        head = text[:keep_head_chars].rstrip()
        cut = len(text) - len(head)
        message["content"] = (
            f"{head}\n... {PRUNED_MARKER} {cut} characters of this {name} output to save context; "
            "call the tool again if you need the full result]"
        )
        removed += cut
    return removed


__all__ = ["PRUNED_MARKER", "prune_stale_tool_outputs"]
