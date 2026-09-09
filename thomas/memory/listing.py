"""Memory snapshot/listing helpers for CLI surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig
from thomas.memory.store import ImmortalLog, MemoryPaths
from thomas.memory.v2 import MemoryFabricV2


def _safe_limit(value: int | None, *, default: int = 20, max_limit: int = 200) -> int:
    try:
        parsed = int(value or default)
    except (ValueError, TypeError):
        parsed = default
    return max(1, min(max_limit, parsed))


def _build_file_entry(path: Path, kind: str, *, identifier: str = "") -> dict[str, Any]:
    stat = path.stat()
    return {
        "kind": kind,
        "id": identifier or path.stem,
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "updated_ts_utc": int(stat.st_mtime),
    }


def _legacy_snapshot_rows(root_path: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = MemoryPaths.from_root(root_path)
    rows: list[dict[str, Any]] = []

    active_name = ""
    active_file = paths.indices_dir / "ACTIVE.json"
    if active_file.exists():
        try:
            payload = json.loads(active_file.read_text(encoding="utf-8"))
            active_name = str(payload.get("active_build") or "").strip()
        except (ValueError, json.JSONDecodeError, OSError):
            active_name = ""

    build_dirs = sorted(
        [path for path in paths.builds_dir.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for build_dir in build_dirs[:limit]:
        base_db = build_dir / "derived_base.db"
        if not base_db.exists():
            continue
        rows.append(
            _build_file_entry(
                base_db,
                "legacy_build",
                identifier=str(build_dir.name),
            )
        )

    delta_db = paths.delta_dir / "derived_delta.db"
    if delta_db.exists():
        rows.append(_build_file_entry(delta_db, "legacy_delta", identifier="delta"))

    events_count = 0
    events_db = paths.data_dir / "events.db"
    if events_db.exists():
        log = ImmortalLog(events_db)
        try:
            events_count = int(log.count_events())
        finally:
            log.close()

    return rows[:limit], {"active_build": active_name, "events_count": events_count}


def _v2_snapshot_rows(root_path: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    db_path = root_path / ".thomas" / "memory_fabric_v2.sqlite3"
    if not db_path.exists():
        return [], {"enabled": False}

    fabric = MemoryFabricV2(root_path=str(db_path.parent))
    try:
        rows = fabric.db.execute(
            "SELECT id, scope, thread_id, tokens_est, waste, updated_at_ms "
            "FROM packs ORDER BY updated_at_ms DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        snapshots = [
            {
                "kind": "v2_pack",
                "id": int(row["id"]),
                "scope": str(row["scope"]),
                "thread_id": str(row["thread_id"] or ""),
                "tokens_est": int(row["tokens_est"]),
                "waste": float(row["waste"]),
                "updated_ts_utc": int(int(row["updated_at_ms"]) / 1000),
            }
            for row in rows
        ]
        health = dict(fabric.health())
        health["enabled"] = True
        return snapshots, health
    finally:
        fabric.db.close()


def list_memory(config: AppConfig, limit: int = 20) -> dict[str, Any]:
    """List available memory snapshots from legacy and v2 stores."""
    root_path = Path(config.memory.root_path)
    max_results = _safe_limit(limit, default=20, max_limit=200)

    legacy_rows, legacy_meta = _legacy_snapshot_rows(root_path, max_results)
    v2_rows, v2_meta = _v2_snapshot_rows(root_path, max_results)

    snapshots = sorted(
        [*legacy_rows, *v2_rows],
        key=lambda row: int(row.get("updated_ts_utc", 0)),
        reverse=True,
    )[:max_results]

    return {
        "ok": True,
        "count": len(snapshots),
        "limit": max_results,
        "snapshots": snapshots,
        "legacy": legacy_meta,
        "v2": v2_meta,
    }
