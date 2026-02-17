"""Thomas Memory Engine — unified facade for memory operations.

Usage:
    from thomas.memory import MemoryEngine
    from thomas.core.config import AppConfig

    engine = MemoryEngine(config)
    engine.start()

    # Record events
    eid = engine.add_event("thread-1", "user_message", "fix the bug in main.py")

    # Retrieve context
    ctx = engine.retrieve("bug in main.py", thread="thread-1")
    print(ctx.text)  # Packed context for LLM injection

    # Ingest new events into index
    engine.ingest_pending()

    # Cleanup
    engine.close()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from thomas.core.config import AppConfig
from thomas.memory.compiler import BaseRebuilder, DeltaIngester
from thomas.memory.embedder import Embedder
from thomas.memory.graph import GraphStore
from thomas.memory.retrieval import PackedContext, RetrievalPipeline
from thomas.memory.store import (
    BlobStore,
    DerivedDB,
    EventRow,
    ImmortalLog,
    IndexManager,
    MemoryPaths,
    MetaDB,
)

log = logging.getLogger(__name__)


class MemoryEngine:
    """Unified facade for all memory operations.

    Manages lifecycle of storage, indexing, and retrieval components.
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._paths = MemoryPaths.from_root(config.memory.root_path)
        self._started = False

        # Components (initialized in start())
        self._log_db: Optional[ImmortalLog] = None
        self._meta_db: Optional[MetaDB] = None
        self._blob_store: Optional[BlobStore] = None
        self._base_derived: Optional[DerivedDB] = None
        self._delta_derived: Optional[DerivedDB] = None
        self._index_mgr: Optional[IndexManager] = None
        self._embedder: Optional[Embedder] = None
        self._graph: Optional[GraphStore] = None
        self._ingester: Optional[DeltaIngester] = None
        self._pipeline: Optional[RetrievalPipeline] = None
        self._rebuilder: Optional[BaseRebuilder] = None

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        """Initialize all memory components."""
        if self._started:
            return

        log.info("Starting memory engine at %s", self._paths.root)
        self._paths.ensure_dirs()

        # Core storage
        self._log_db = ImmortalLog(self._paths.data_dir / "events.db")
        self._meta_db = MetaDB(self._paths.data_dir / "meta.db")
        self._blob_store = BlobStore(self._paths.blobs_dir)

        # Index manager + bootstrap
        self._index_mgr = IndexManager(self._paths.indices_dir)
        self._index_mgr.ensure_bootstrap()

        # Derived DBs (base + delta)
        self._base_derived = DerivedDB(self._index_mgr.active_base_path())
        self._delta_derived = DerivedDB(self._index_mgr.delta_path())

        # Embedder
        self._embedder = Embedder(self._config.embed)

        # Graph store (operates on delta)
        self._graph = GraphStore(self._delta_derived)

        # Delta ingester
        self._ingester = DeltaIngester(
            self._log_db, self._delta_derived, self._graph, self._embedder
        )

        # Retrieval pipeline
        self._pipeline = RetrievalPipeline(
            log_db=self._log_db,
            meta_db=self._meta_db,
            base_derived=self._base_derived,
            delta_derived=self._delta_derived,
            graph=self._graph,
            embedder=self._embedder,
            config=self._config.memory,
        )

        # Base rebuilder
        self._rebuilder = BaseRebuilder(
            self._log_db, self._index_mgr, self._embedder, self._paths
        )

        self._started = True
        log.info(
            "Memory engine started. events=%d, dense=%s",
            self._log_db.count_events(),
            self._embedder.has_dense,
        )

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("MemoryEngine.start() must be called first")

    # ----- Event operations -----

    def add_event(
        self,
        thread: str,
        etype: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        blob_id: Optional[str] = None,
    ) -> int:
        """Add an event to the immortal log. Returns event ID."""
        self._require_started()
        if self._log_db is None:
            raise RuntimeError("Memory log database is not initialized")
        return self._log_db.add_event(thread, etype, text, metadata, blob_id)

    def recent_events(self, thread: str, limit: int = 20) -> List[EventRow]:
        """Get recent events for a thread."""
        self._require_started()
        if self._log_db is None:
            raise RuntimeError("Memory log database is not initialized")
        return self._log_db.recent_events(thread, limit)

    # ----- Blob operations -----

    def store_blob(self, data: bytes) -> str:
        """Store a blob, returns SHA256 hash ID."""
        self._require_started()
        if self._blob_store is None:
            raise RuntimeError("Blob store is not initialized")
        return self._blob_store.put_bytes(data)

    def get_blob(self, blob_id: str) -> bytes:
        """Retrieve blob by hash ID."""
        self._require_started()
        if self._blob_store is None:
            raise RuntimeError("Blob store is not initialized")
        return self._blob_store.get_bytes(blob_id)

    # ----- Pin operations -----

    def pin(self, key: str, text: str) -> None:
        """Set a user pin (always included in context)."""
        self._require_started()
        if self._meta_db is None:
            raise RuntimeError("Metadata database is not initialized")
        self._meta_db.pin_set(key, text)

    def unpin(self, key: str) -> None:
        """Remove a user pin."""
        self._require_started()
        if self._meta_db is None:
            raise RuntimeError("Metadata database is not initialized")
        self._meta_db.pin_rm(key)

    def list_pins(self) -> List[Tuple[str, str, int]]:
        """List all pins as (key, text, timestamp)."""
        self._require_started()
        if self._meta_db is None:
            raise RuntimeError("Metadata database is not initialized")
        return self._meta_db.pin_list()

    # ----- Retrieval -----

    def retrieve(
        self,
        query: str,
        thread: Optional[str] = None,
        budget: Optional[int] = None,
        mode: str = "auto",
    ) -> PackedContext:
        """Retrieve memory context for a query.

        Returns PackedContext with text ready for LLM injection.
        """
        self._require_started()
        if self._pipeline is None:
            raise RuntimeError("Retrieval pipeline is not initialized")
        return self._pipeline.retrieve(query, thread, budget, mode)

    # ----- Ingestion -----

    def ingest_pending(self) -> Dict[str, Any]:
        """Ingest any new events since last ingestion."""
        self._require_started()
        if self._ingester is None:
            raise RuntimeError("Delta ingester is not initialized")
        return self._ingester.ingest_new()

    def ingest_events(self, events: List[EventRow]) -> Dict[str, Any]:
        """Ingest specific events into the delta index."""
        self._require_started()
        if self._ingester is None:
            raise RuntimeError("Delta ingester is not initialized")
        return self._ingester.ingest_events(events)

    # ----- Rebuild -----

    def rebuild_base(self) -> Dict[str, Any]:
        """Rebuild base index from scratch (nightly operation)."""
        self._require_started()
        if self._rebuilder is None:
            raise RuntimeError("Base rebuilder is not initialized")
        return self._rebuilder.rebuild()

    # ----- Stats -----

    def stats(self) -> Dict[str, Any]:
        """Get memory engine statistics."""
        self._require_started()
        if self._log_db is None or self._embedder is None:
            raise RuntimeError("Memory engine components are not initialized")
        return {
            "event_count": self._log_db.count_events(),
            "has_dense": self._embedder.has_dense,
            "dense_dim": self._embedder.dense_dim if self._embedder.has_dense else 0,
            "root": str(self._paths.root),
        }

    def recent_traces(self, thread: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent retrieval traces for debugging and memory observability."""
        self._require_started()
        if self._meta_db is None:
            raise RuntimeError("Metadata database is not initialized")
        return self._meta_db.trace_recent(thread=thread, limit=limit)

    def diagnostics(self, thread: Optional[str] = None, trace_limit: int = 8) -> Dict[str, Any]:
        """Combined memory diagnostics payload for UI/API surfaces."""
        self._require_started()
        stats = self.stats()
        pins = self.list_pins()
        traces = self.recent_traces(thread=thread, limit=trace_limit)
        return {
            "stats": stats,
            "pins": [
                {"key": k, "text": t, "created_ts_utc": ts}
                for k, t, ts in pins
            ],
            "traces": traces,
        }

    # ----- Lifecycle -----

    def close(self) -> None:
        """Close all database connections and free resources."""
        if not self._started:
            return
        log.info("Closing memory engine")
        if self._embedder:
            self._embedder.unload_dense()
        for db in (self._log_db, self._meta_db, self._base_derived, self._delta_derived):
            if db is not None:
                db.close()
        self._started = False
