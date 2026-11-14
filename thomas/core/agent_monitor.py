"""Which running tasks have stopped making progress: the Agents workspace lifts these to the top of its board.

A task is stalled when it is ``running`` and its ``updated_at`` is older than the limit. Queued and awaiting-approval
tasks are waiting on something else, and finished ones are done, so none of them is called stalled.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

DEFAULT_STALLED_AFTER_S = 600.0
LIMIT_ENV = "THOMAS_STALLED_AFTER_S"


def stalled_after_s() -> float:
    """Seconds without progress before a running task is stalled. A value that is not a positive number is the default."""
    raw = str(os.environ.get(LIMIT_ENV) or "").strip()
    if not raw:
        return DEFAULT_STALLED_AFTER_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_STALLED_AFTER_S
    return value if value > 0 else DEFAULT_STALLED_AFTER_S


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def mark_stalled(agents: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    """Copies of ``agents`` with ``stalled`` (bool) and ``idle_s`` (seconds since ``updated_at``, or None) added."""
    moment = now or datetime.now(timezone.utc)
    limit = stalled_after_s()
    marked: list[dict[str, Any]] = []
    for agent in agents:
        updated = _parse(agent.get("updated_at"))
        idle = max(int((moment - updated).total_seconds()), 0) if updated else None
        running = str(agent.get("status") or "").strip().lower() == "running"
        marked.append({**agent, "stalled": bool(running and idle is not None and idle > limit), "idle_s": idle})
    return marked
