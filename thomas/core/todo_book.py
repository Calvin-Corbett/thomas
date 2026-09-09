"""The checklist the model keeps while it works, and the page shows.

Frontier parity with Claude Code's TodoWrite: for multi-step work the model
writes a short list, marks one item in progress, ticks items off, and the
person sees the plan and the progress instead of a spinner. One
process-wide book in core, like the question book (tools may not import thomas.agent); Thomas is a one-person product.
A write replaces the list for its session; an empty write clears it.
"""

from __future__ import annotations

import time
from typing import Any

STATUSES = ("pending", "in_progress", "done")
MAX_ITEMS = 30


def normalize_items(raw: Any) -> list[dict[str, str]]:
    """Keep well-formed items only: non-empty text, a known status (default pending)."""
    items: list[dict[str, str]] = []
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, str):
            entry = {"text": entry}
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        status = str(entry.get("status") or "pending").strip().lower()
        if status not in STATUSES:
            status = "pending"
        items.append({"text": text[:300], "status": status})
        if len(items) >= MAX_ITEMS:
            break
    return items


class TodoBook:
    def __init__(self) -> None:
        self._lists: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def write(self, session_id: str, *, title: str, items: Any) -> dict[str, Any] | None:
        """Replace the session's list. Returns the record, or None when the list was cleared."""
        key = str(session_id or "").strip() or "current"
        clean = normalize_items(items)
        if not clean:
            self._lists.pop(key, None)
            return None
        self._seq += 1
        record = {
            "session_id": key,
            "title": str(title or "").strip()[:120],
            "items": clean,
            "updated_at": time.time(),
            "_seq": self._seq,  # two writes in one clock tick still order newest first
        }
        self._lists[key] = record
        return dict(record, items=[dict(i) for i in clean])

    def get(self, session_id: str) -> dict[str, Any] | None:
        record = self._lists.get(str(session_id or "").strip() or "current")
        return dict(record, items=[dict(i) for i in record["items"]]) if record else None

    def all(self) -> list[dict[str, Any]]:
        rows = sorted(self._lists.values(), key=lambda r: (r["updated_at"], r["_seq"]), reverse=True)
        return [dict(r, items=[dict(i) for i in r["items"]]) for r in rows]

    def clear(self, session_id: str) -> None:
        self._lists.pop(str(session_id or "").strip() or "current", None)


_BOOK = TodoBook()


def todo_book() -> TodoBook:
    """The process-wide book the tool and the route share."""
    return _BOOK


__all__ = ["MAX_ITEMS", "STATUSES", "TodoBook", "normalize_items", "todo_book"]
