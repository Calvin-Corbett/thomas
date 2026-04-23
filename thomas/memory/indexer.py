"""Memory index maintenance helpers for CLI surfaces."""

from __future__ import annotations

from typing import Any

from thomas.core.config import AppConfig
from thomas.memory import MemoryEngine


def reindex_memory(config: AppConfig) -> dict[str, Any]:
    """Ingest pending events into memory indexes."""
    engine = MemoryEngine(config)
    engine.start()
    try:
        ingest = dict(engine.ingest_pending())
        stats = dict(engine.stats())
        indexed = int(ingest.get("indexed") or ingest.get("processed") or 0)
        return {
            "ok": True,
            "indexed": indexed,
            "ingest": ingest,
            "event_count": int(stats.get("event_count") or 0),
            "has_dense": bool(stats.get("has_dense")),
        }
    finally:
        engine.close()
