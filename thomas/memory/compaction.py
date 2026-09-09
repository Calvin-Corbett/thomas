"""Memory compaction helpers for CLI surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig
from thomas.memory.v2 import MemoryFabricV2


def _safe_limit(value: int, *, default: int = 5, max_limit: int = 25) -> int:
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        parsed = default
    return max(1, min(max_limit, parsed))


def compact_memory(config: AppConfig, *, thread_limit: int = 5) -> dict[str, Any]:
    """Compact global memory pack and recent thread packs in Memory Fabric v2."""
    root_path = Path(config.memory.root_path) / ".thomas"
    fabric = MemoryFabricV2(root_path=str(root_path))
    try:
        max_threads = _safe_limit(thread_limit, default=5, max_limit=25)
        rows = fabric.db.execute(
            "SELECT thread_id, MAX(ts_ms) AS latest_ts_ms "
            "FROM episodes "
            "WHERE thread_id IS NOT NULL AND thread_id <> '' "
            "GROUP BY thread_id "
            "ORDER BY latest_ts_ms DESC LIMIT ?",
            (int(max_threads),),
        ).fetchall()

        compacted_threads: list[dict[str, Any]] = []
        for row in rows:
            thread_id = str(row["thread_id"])
            result = fabric.compact(thread_id=thread_id)
            compacted_threads.append({"thread_id": thread_id, "result": dict(result)})

        global_result = fabric.compact(thread_id=None)
        return {
            "ok": True,
            "global": dict(global_result),
            "threads": compacted_threads,
            "thread_count": len(compacted_threads),
            "health": dict(fabric.health()),
        }
    finally:
        fabric.db.close()
