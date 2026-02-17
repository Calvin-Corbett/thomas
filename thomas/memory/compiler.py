"""Memory compiler: delta ingestion and nightly base rebuilds.

Handles two operations:
1. ingest_delta — process new events into the delta index (embeddings + graph)
2. rebuild_base — merge delta into a new base build (nightly/manual)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from thomas.memory.embedder import Embedder
from thomas.memory.graph import GraphStore
from thomas.memory.store import (
    DerivedDB,
    EventRow,
    ImmortalLog,
    IndexManager,
    MemoryPaths,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Delta ingestion
# ---------------------------------------------------------------------------


class DeltaIngester:
    """Ingest new events into the delta index.

    Called after each conversation turn to keep the delta
    index up-to-date with new events.
    """

    def __init__(
        self,
        log_db: ImmortalLog,
        delta_derived: DerivedDB,
        graph: GraphStore,
        embedder: Embedder,
    ):
        self._log = log_db
        self._delta = delta_derived
        self._graph = graph
        self._embedder = embedder
        self._last_indexed_id: int = 0

    @property
    def last_indexed_id(self) -> int:
        return self._last_indexed_id

    @last_indexed_id.setter
    def last_indexed_id(self, value: int) -> None:
        self._last_indexed_id = value

    def ingest_events(self, events: List[EventRow]) -> Dict[str, Any]:
        """Index a batch of events into delta derived DB.

        Returns stats dict with counts.
        """
        if not events:
            return {"indexed": 0}

        start = time.monotonic()
        texts = [ev.text for ev in events]

        # 1. Sparse embeddings (always)
        sparse_vecs = self._embedder.sparse_batch(texts)

        # 2. Dense embeddings (if available)
        dense_blobs = self._embedder.dense_bytes_batch(texts)

        # 3. Store vectors
        for ev, svec, dblob in zip(events, sparse_vecs, dense_blobs):
            self._delta.vec_upsert(
                event_id=ev.id,
                thread=ev.thread,
                ts_utc=ev.ts_utc,
                etype=ev.etype,
                vec=svec,
                vec_dense=dblob,
            )

        # 4. Extract and store graph entities
        all_text = "\n".join(texts)
        e_count, r_count = self._graph.ingest_text(
            all_text, event_ids=[ev.id for ev in events]
        )

        # Track progress
        if events:
            self._last_indexed_id = max(ev.id for ev in events)

        duration = (time.monotonic() - start) * 1000
        stats = {
            "indexed": len(events),
            "entities": e_count,
            "relations": r_count,
            "has_dense": self._embedder.has_dense,
            "duration_ms": duration,
        }
        log.info("Delta ingestion: %d events in %.0fms", len(events), duration)
        return stats

    def ingest_new(self) -> Dict[str, Any]:
        """Ingest all events newer than last_indexed_id."""
        new_events = list(self._log.iter_events(after_id=self._last_indexed_id))

        if not new_events:
            return {"indexed": 0}

        # Process in batches to avoid memory spikes
        batch_size = 64
        total_stats: Dict[str, Any] = {"indexed": 0, "entities": 0, "relations": 0}

        for i in range(0, len(new_events), batch_size):
            batch = new_events[i:i + batch_size]
            stats = self.ingest_events(batch)
            total_stats["indexed"] += stats["indexed"]
            total_stats["entities"] += stats["entities"]
            total_stats["relations"] += stats["relations"]

        total_stats["has_dense"] = self._embedder.has_dense
        return total_stats


# ---------------------------------------------------------------------------
# Base rebuild (nightly)
# ---------------------------------------------------------------------------


class BaseRebuilder:
    """Rebuild the base index from scratch.

    Reads all events from ImmortalLog, computes embeddings,
    and creates a new base build. Then atomically swaps it active.
    """

    def __init__(
        self,
        log_db: ImmortalLog,
        index_mgr: IndexManager,
        embedder: Embedder,
        paths: MemoryPaths,
    ):
        self._log = log_db
        self._index_mgr = index_mgr
        self._embedder = embedder
        self._paths = paths

    def rebuild(self) -> Dict[str, Any]:
        """Full rebuild of the base index.

        Creates a new build, indexes all events, then swaps it active.
        The old base stays on disk until the next rebuild.
        """
        start = time.monotonic()
        build_name = f"build_{int(time.time())}"
        build_dir = self._index_mgr.new_build_dir(build_name)

        log.info("Starting base rebuild: %s", build_name)

        # Create fresh derived DB
        new_derived = DerivedDB(build_dir / "derived_base.db")
        new_graph = GraphStore(new_derived)

        # Process all events in batches
        batch: List[EventRow] = []
        batch_size = 64
        total = 0
        e_count = 0
        r_count = 0

        for event in self._log.iter_events():
            batch.append(event)
            if len(batch) >= batch_size:
                stats = self._process_batch(batch, new_derived, new_graph)
                total += stats["indexed"]
                e_count += stats["entities"]
                r_count += stats["relations"]
                batch = []

        # Final batch
        if batch:
            stats = self._process_batch(batch, new_derived, new_graph)
            total += stats["indexed"]
            e_count += stats["entities"]
            r_count += stats["relations"]

        new_derived.close()

        # Swap to new base
        self._index_mgr.set_active(build_name)

        # Clear delta (it's now merged into base)
        delta_path = self._paths.delta_dir / "derived_delta.db"
        if delta_path.exists():
            delta_path.unlink()

        duration = (time.monotonic() - start) * 1000
        stats = {
            "build_name": build_name,
            "events_indexed": total,
            "entities": e_count,
            "relations": r_count,
            "duration_ms": duration,
        }
        log.info("Base rebuild complete: %d events in %.1fs", total, duration / 1000)
        return stats

    def _process_batch(
        self,
        events: List[EventRow],
        derived: DerivedDB,
        graph: GraphStore,
    ) -> Dict[str, Any]:
        """Process a batch of events for the rebuild."""
        texts = [ev.text for ev in events]

        # Sparse + dense embeddings
        sparse_vecs = self._embedder.sparse_batch(texts)
        dense_blobs = self._embedder.dense_bytes_batch(texts)

        for ev, svec, dblob in zip(events, sparse_vecs, dense_blobs):
            derived.vec_upsert(
                event_id=ev.id,
                thread=ev.thread,
                ts_utc=ev.ts_utc,
                etype=ev.etype,
                vec=svec,
                vec_dense=dblob,
            )

        # Graph extraction
        all_text = "\n".join(texts)
        e_count, r_count = graph.ingest_text(
            all_text, event_ids=[ev.id for ev in events]
        )

        return {"indexed": len(events), "entities": e_count, "relations": r_count}
