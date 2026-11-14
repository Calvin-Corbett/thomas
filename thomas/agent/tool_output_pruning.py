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


def _stale(message: Any, min_chars: int) -> bool:
    if not isinstance(message, dict) or message.get("role") != "tool":
        return False
    text = _text_of(message.get("content"))
    return text is not None and len(text) > min_chars and PRUNED_MARKER not in text[-200:]


def prune_stale_tool_outputs(
    conversation: list[dict[str, Any]],
    *,
    keep_recent_messages: int = 12,
    min_chars: int = 2000,
    keep_head_chars: int = 400,
    min_batch: int = 1,
) -> int:
    """Replace large, old tool outputs in place. Returns the number of characters removed.

    A message is old when it sits before the last ``keep_recent_messages``
    messages. Only ``role == "tool"`` string contents longer than ``min_chars``
    are touched; user and assistant text, tool_call ids and names all stay.

    Nothing is cut until at least *min_batch* outputs are old enough, and then they are cut together. Each cut
    rewrites an earlier part of the request, so the provider's cache serves nothing after it on the next call; one
    output stubbed per call was a break on every call (41% of Build's requests, 2026-11-06).
    """
    if not isinstance(conversation, list) or keep_recent_messages < 0:
        return 0
    cutoff = max(0, len(conversation) - keep_recent_messages)
    stale = [message for message in conversation[:cutoff] if _stale(message, min_chars)]
    if len(stale) < max(1, int(min_batch)):
        return 0
    removed = 0
    for message in stale:
        text = str(message["content"])
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
