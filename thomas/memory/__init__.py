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
import os

# Episodic memory system
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from thomas.core.config import AppConfig
from thomas.memory.compiler import BaseRebuilder, DeltaIngester
from thomas.memory.embedder import Embedder

_EPISODIC_FALLBACK_ACTIVE = False
_EPISODIC_FALLBACK_REASON = ""


def _legacy_memory_enabled() -> bool:
    raw = os.environ.get("THOMAS_MEMORY_LEGACY_ENABLED")
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


try:
    from thomas.memory.episodic import (
        Episode,
        EpisodeStore,
        EpisodicMemory,
        MemoryRetriever,
        SimpleEmbedder,
    )
except (AttributeError, ImportError) as exc:
    _EPISODIC_FALLBACK_ACTIVE = True
    _EPISODIC_FALLBACK_REASON = f"{type(exc).__name__}: {exc}"

    @dataclass
    class Episode:
        text: str
        thread_id: str | None = None
        metadata: dict[str, object] | None = None

    class EpisodeStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.episodes: list[Episode] = []

        def add(self, episode: Episode) -> None:
            self.episodes.append(episode)

        def search(
            self,
            query: str,
            *,
            thread_id: str | None = None,
            limit: int = 5,
        ) -> list[Episode]:
            query_text = str(query or "").strip().lower()
            if not query_text:
                return []
            tokens = [token for token in query_text.split() if token]
            scored: list[tuple[int, int, Episode]] = []
            for reverse_index, episode in enumerate(reversed(self.episodes)):
                if thread_id and episode.thread_id != thread_id:
                    continue
                haystack = episode.text.lower()
                score = 0
                if query_text in haystack:
                    score += len(query_text) + 10
                score += sum(1 for token in tokens if token in haystack)
                if score:
                    scored.append((score, reverse_index, episode))
            scored.sort(key=lambda item: (-item[0], item[1]))
            return [episode for _, _, episode in scored[: max(1, limit)]]

    class EpisodicMemory:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.store = EpisodeStore()

        def add(self, episode: Episode) -> None:
            self.store.add(episode)

        def query(
            self,
            query: str,
            *,
            thread_id: str | None = None,
            limit: int = 5,
        ) -> list[Episode]:
            return self.store.search(query, thread_id=thread_id, limit=limit)

    class MemoryRetriever:
        def __init__(self, memory: EpisodicMemory | None = None, *_args: object, **_kwargs: object) -> None:
            self.memory = memory

        def retrieve(
            self,
            query: str,
            *,
            thread_id: str | None = None,
            limit: int = 5,
            **_kwargs: object,
        ) -> list[Episode]:
            if self.memory is None:
                return []
            return self.memory.query(query, thread_id=thread_id, limit=limit)

    class SimpleEmbedder:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.has_dense = False
            self.dense_dim = 0

        def embed(self, text: str) -> list[float]:
            return [float(len(text))]


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

if _EPISODIC_FALLBACK_ACTIVE and _legacy_memory_enabled():
    log.warning(
        "Episodic memory module unavailable; using minimal fallback retriever: %s",
        _EPISODIC_FALLBACK_REASON,
    )


class MemoryEngine:
    """Unified facade for all memory operations.

    Manages lifecycle of storage, indexing, and retrieval components.
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._paths = MemoryPaths.from_root(config.memory.root_path)
        self._started = False

        # Components (initialized in start())
        self._log_db: ImmortalLog | None = None
        self._meta_db: MetaDB | None = None
        self._blob_store: BlobStore | None = None
        self._base_derived: DerivedDB | None = None
        self._delta_derived: DerivedDB | None = None
        self._index_mgr: IndexManager | None = None
        self._embedder: Embedder | None = None
        self._graph: GraphStore | None = None
        self._ingester: DeltaIngester | None = None
        self._pipeline: RetrievalPipeline | None = None
        self._rebuilder: BaseRebuilder | None = None

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
        self._ingester = DeltaIngester(self._log_db, self._delta_derived, self._graph, self._embedder)

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
        self._rebuilder = BaseRebuilder(self._log_db, self._index_mgr, self._embedder, self._paths)

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
        metadata: dict[str, Any] | None = None,
        blob_id: str | None = None,
    ) -> int:
        """Add an event to the immortal log. Returns event ID."""
        self._require_started()
        if self._log_db is None:
            raise RuntimeError("Memory log database is not initialized")
        return self._log_db.add_event(thread, etype, text, metadata, blob_id)

    def recent_events(self, thread: str, limit: int = 20) -> list[EventRow]:
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

    def list_pins(self) -> list[tuple[str, str, int]]:
        """List all pins as (key, text, timestamp)."""
        self._require_started()
        if self._meta_db is None:
            raise RuntimeError("Metadata database is not initialized")
        return self._meta_db.pin_list()

    # ----- Retrieval -----

    def retrieve(
        self,
        query: str,
        thread: str | None = None,
        budget: int | None = None,
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

    def ingest_pending(self) -> dict[str, Any]:
        """Ingest any new events since last ingestion."""
        self._require_started()
        if self._ingester is None:
            raise RuntimeError("Delta ingester is not initialized")
        return self._ingester.ingest_new()

    def ingest_events(self, events: list[EventRow]) -> dict[str, Any]:
        """Ingest specific events into the delta index."""
        self._require_started()
        if self._ingester is None:
            raise RuntimeError("Delta ingester is not initialized")
        return self._ingester.ingest_events(events)

    # ----- Rebuild -----

    def rebuild_base(self) -> dict[str, Any]:
        """Rebuild base index from scratch (nightly operation)."""
        self._require_started()
        if self._rebuilder is None:
            raise RuntimeError("Base rebuilder is not initialized")
        return self._rebuilder.rebuild()

    # ----- Stats -----

    def stats(self) -> dict[str, Any]:
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

    def recent_traces(self, thread: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent retrieval traces for debugging and memory observability."""
        self._require_started()
        if self._meta_db is None:
            raise RuntimeError("Metadata database is not initialized")
        return self._meta_db.trace_recent(thread=thread, limit=limit)

    def diagnostics(self, thread: str | None = None, trace_limit: int = 8) -> dict[str, Any]:
        """Combined memory diagnostics payload for UI/API surfaces."""
        self._require_started()
        stats = self.stats()
        pins = self.list_pins()
        traces = self.recent_traces(thread=thread, limit=trace_limit)
        return {
            "stats": stats,
            "pins": [{"key": k, "text": t, "created_ts_utc": ts} for k, t, ts in pins],
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
