"""Memory search helpers for CLI/runtime command surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig
from thomas.memory.store import ImmortalLog, MemoryPaths
from thomas.memory.v2 import MemoryFabricV2


def _preview(text: str, *, max_chars: int = 180) -> str:
    one_line = " ".join(str(text or "").split())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[: max_chars - 3].rstrip() + "..."


def _safe_limit(value: int | None, *, default: int = 10, max_limit: int = 200) -> int:
    try:
        parsed = int(value or default)
    except (ValueError, TypeError):
        parsed = default
    return max(1, min(max_limit, parsed))


def _legacy_event_matches(root_path: Path, query: str, *, limit: int) -> list[dict[str, Any]]:
    events_db = MemoryPaths.from_root(root_path).data_dir / "events.db"
    if not events_db.exists():
        return []

    log = ImmortalLog(events_db)
    try:
        ranked = log.search_fts(query, limit=max(limit * 3, limit))
        if not ranked:
            return []
        event_ids = [int(event_id) for event_id, _score in ranked]
        by_id = log.get_events_batch(event_ids)
        rows: list[dict[str, Any]] = []
        for event_id, score in ranked:
            row = by_id.get(int(event_id))
            if row is None:
                continue
            rows.append(
                {
                    "source": "legacy_event",
                    "id": int(row.id),
                    "thread": str(row.thread),
                    "etype": str(row.etype),
                    "ts_utc": int(row.ts_utc),
                    "score": float(score),
                    "preview": _preview(str(row.text)),
                }
            )
            if len(rows) >= limit:
                break
        return rows
    finally:
        log.close()


def _v2_matches(root_path: Path, query: str, *, limit: int) -> list[dict[str, Any]]:
    fabric_db = root_path / ".thomas" / "memory_fabric_v2.sqlite3"
    if not fabric_db.exists():
        return []

    needle = f"%{str(query or '').strip()}%"
    if not needle or needle == "%%":
        return []

    fabric = MemoryFabricV2(root_path=str(fabric_db.parent))
    try:
        episodes = fabric.db.execute(
            "SELECT id, thread_id, role, content, ts_ms FROM episodes WHERE content LIKE ? ORDER BY ts_ms DESC LIMIT ?",
            (needle, int(limit)),
        ).fetchall()
        facts = fabric.db.execute(
            "SELECT id, thread_id, ts_ms, subject, predicate, obj, confidence "
            "FROM semantic_facts "
            "WHERE subject LIKE ? OR predicate LIKE ? OR obj LIKE ? "
            "ORDER BY ts_ms DESC LIMIT ?",
            (needle, needle, needle, int(limit)),
        ).fetchall()

        rows: list[dict[str, Any]] = []
        for row in episodes:
            rows.append(
                {
                    "source": "v2_episode",
                    "id": int(row["id"]),
                    "thread": str(row["thread_id"]),
                    "etype": str(row["role"]),
                    "ts_utc": int(int(row["ts_ms"]) / 1000),
                    "score": 0.6,
                    "preview": _preview(str(row["content"])),
                }
            )
        for row in facts:
            snippet = f"{row['subject']} {row['predicate']} {row['obj']} (conf {float(row['confidence']):.2f})"
            rows.append(
                {
                    "source": "v2_fact",
                    "id": int(row["id"]),
                    "thread": str(row["thread_id"] or ""),
                    "etype": "fact",
                    "ts_utc": int(int(row["ts_ms"]) / 1000),
                    "score": 0.55,
                    "preview": _preview(snippet),
                }
            )

        rows.sort(key=lambda item: (int(item.get("ts_utc", 0)), float(item.get("score", 0.0))), reverse=True)
        return rows[:limit]
    finally:
        fabric.db.close()


def search_memory(config: AppConfig, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search memory backends and return normalized result rows."""
    query_text = str(query or "").strip()
    if not query_text:
        return []

    root_path = Path(config.memory.root_path)
    max_results = _safe_limit(limit, default=10, max_limit=200)

    merged: list[dict[str, Any]] = []
    merged.extend(_legacy_event_matches(root_path, query_text, limit=max_results))
    merged.extend(_v2_matches(root_path, query_text, limit=max_results))

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in sorted(
        merged,
        key=lambda item: (int(item.get("ts_utc", 0)), float(item.get("score", 0.0))),
        reverse=True,
    ):
        key = f"{row.get('source')}:{row.get('id')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= max_results:
            break
    return deduped
