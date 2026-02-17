"""Retrieval pipeline: multi-source search, reranking, context packing.

The pipeline:
1. Expand query (lexicon translation)
2. Multi-source retrieval: FTS (BM25) + sparse vectors + graph
3. Merge via Reciprocal Rank Fusion (RRF)
4. Batch-load events (fixes N+1 query pattern)
5. Tier 1 reranking (feature-based)
6. Tier 2 reranking (dense similarity, optional)
7. Pack into context budget
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from thomas.core.config import AppConfig, EmbedConfig, MemoryConfig
from thomas.memory.embedder import Embedder, bytes_to_dense, cosine_similarity_dense
from thomas.memory.graph import GraphStore
from thomas.memory.rerank import (
    CandidateFeatures,
    Tier1Reranker,
    Tier2Reranker,
    reciprocal_rank_fusion,
)
from thomas.memory.store import (
    DerivedDB,
    EventRow,
    ImmortalLog,
    MetaDB,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context packing
# ---------------------------------------------------------------------------


@dataclass
class PackedContext:
    """Memory context ready for injection into LLM prompt."""

    text: str = ""
    event_count: int = 0
    token_estimate: int = 0
    sources: List[str] = field(default_factory=list)
    trace: Dict[str, Any] = field(default_factory=dict)


def pack_context(
    events: List[EventRow],
    budget: int = 12000,
    graph_summary: str = "",
    pins: Optional[List[Tuple[str, str, int]]] = None,
) -> PackedContext:
    """Pack retrieved events into a context string within token budget.

    Token estimation: ~4 chars per token (rough approximation).

    Args:
        events: Ordered events to pack (most relevant first)
        budget: Maximum token budget
        graph_summary: Graph context summary to prepend
        pins: User pins to always include [(key, text, ts)]

    Returns:
        PackedContext with assembled text and metadata
    """
    char_budget = budget * 4  # ~4 chars per token
    parts: List[str] = []
    sources: List[str] = []
    used_chars = 0
    packed_events = 0

    # Always include pins first (they're user-prioritized)
    if pins:
        pin_lines = []
        for key, text, _ts in pins:
            pin_lines.append(f"[pin:{key}] {text}")
        pin_block = "## Pinned Context\n" + "\n".join(pin_lines) + "\n\n"
        parts.append(pin_block)
        used_chars += len(pin_block)
        sources.append(f"pins:{len(pins)}")

    # Include graph context if available
    if graph_summary:
        graph_block = f"## Knowledge Graph\n{graph_summary}\n\n"
        if used_chars + len(graph_block) < char_budget:
            parts.append(graph_block)
            used_chars += len(graph_block)
            sources.append("graph")

    # Pack events (most relevant first)
    if events:
        parts.append("## Retrieved Memory\n")
        used_chars += 22
        packed_count = 0

        for ev in events:
            # Format event
            line = f"[{ev.etype}@{ev.ts_utc}] {ev.text}\n"
            if used_chars + len(line) > char_budget:
                break
            parts.append(line)
            used_chars += len(line)
            packed_count += 1

        sources.append(f"events:{packed_count}")
        packed_events = packed_count

    text = "".join(parts).rstrip()
    token_est = len(text) // 4

    return PackedContext(
        text=text,
        event_count=len(events),
        token_estimate=token_est,
        sources=sources,
        trace={
            "budget": budget,
            "chars_used": used_chars,
            "events_offered": len(events),
            "events_packed": packed_events,
        },
    )


# ---------------------------------------------------------------------------
# Retrieval Pipeline
# ---------------------------------------------------------------------------


class RetrievalPipeline:
    """Multi-source retrieval with reranking and context packing.

    Orchestrates: FTS + sparse vec + graph → RRF → Tier1 → Tier2 → pack.
    """

    def __init__(
        self,
        log_db: ImmortalLog,
        meta_db: MetaDB,
        base_derived: DerivedDB,
        delta_derived: DerivedDB,
        graph: GraphStore,
        embedder: Embedder,
        config: MemoryConfig,
    ):
        self._log = log_db
        self._meta = meta_db
        self._base = base_derived
        self._delta = delta_derived
        self._graph = graph
        self._embedder = embedder
        self._config = config
        self._tier1 = Tier1Reranker()
        self._tier2 = Tier2Reranker()

    def retrieve(
        self,
        query: str,
        thread: Optional[str] = None,
        budget: Optional[int] = None,
        mode: str = "auto",
    ) -> PackedContext:
        """Run the full retrieval pipeline.

        Args:
            query: User query / latest message
            thread: Thread ID to scope search (None = all threads)
            budget: Token budget override (default from config)
            mode: Retrieval mode — "auto", "fast", "thorough"

        Returns:
            PackedContext ready for LLM injection
        """
        start = time.monotonic()
        budget = budget or self._config.context_budget
        trace: Dict[str, Any] = {"query": query, "thread": thread, "mode": mode}

        # 1. Expand query via lexicon
        expanded = self._meta.lex_translate(query)
        if expanded != query:
            trace["expanded_query"] = expanded

        # 2. Sparse embedding of query
        q_sparse = self._embedder.sparse(expanded)

        # 3. Multi-source retrieval
        fts_results = self._search_fts(expanded, thread)
        sparse_results = self._search_sparse(q_sparse, thread)
        graph_ctx = self._graph.get_context(expanded)

        trace["fts_hits"] = len(fts_results)
        trace["sparse_hits"] = len(sparse_results)
        trace["graph_entities"] = len(graph_ctx.entities)

        # 4. Merge via RRF
        merged = reciprocal_rank_fusion(fts_results, sparse_results)

        # Add graph-connected event IDs with bonus
        for rel in graph_ctx.relations:
            for receipt in rel.get("receipts", []):
                if isinstance(receipt, int):
                    merged[receipt] = merged.get(receipt, 0.0) + 0.05

        if not merged:
            # No results — return empty context
            trace["duration_ms"] = (time.monotonic() - start) * 1000
            return PackedContext(trace=trace)

        # 5. Batch-load events (fixes N+1)
        event_ids = list(merged.keys())
        events = self._log.get_events_batch(event_ids)
        trace["events_loaded"] = len(events)

        # 6. Build candidate features
        candidates: List[CandidateFeatures] = []
        for eid, rrf_score in merged.items():
            if eid not in events:
                continue
            ev = events[eid]
            # Find individual scores
            fts_score = dict(fts_results).get(eid, 0.0)
            sparse_score = dict(sparse_results).get(eid, 0.0)

            candidates.append(CandidateFeatures(
                event_id=eid,
                event=ev,
                fts_score=fts_score,
                sparse_score=sparse_score,
            ))

        # 7. Tier 1 reranking
        candidates = self._tier1.score(candidates)

        # 8. Tier 2 reranking (if dense embeddings available and mode allows)
        top_k = 50 if mode == "thorough" else 30
        candidates = candidates[:top_k]

        if self._embedder.has_dense and mode != "fast":
            candidates = self._tier2_rerank(expanded, candidates)
            trace["tier2_applied"] = True

        # 9. Get pins
        pins = self._meta.pin_list()

        # 10. Pack context
        ordered_events = [c.event for c in candidates if c.event is not None]
        result = pack_context(
            events=ordered_events,
            budget=budget,
            graph_summary=graph_ctx.summary,
            pins=pins,
        )

        # Record trace
        trace["duration_ms"] = (time.monotonic() - start) * 1000
        trace["final_candidates"] = len(candidates)
        result.trace.update(trace)

        # Save trace for debugging
        self._meta.trace_add(
            thread=thread or "global",
            mode=mode,
            query=query,
            trace=trace,
        )

        return result

    def _search_fts(
        self, query: str, thread: Optional[str]
    ) -> List[Tuple[int, float]]:
        """Full-text search via BM25."""
        try:
            return self._log.search_fts(query, thread=thread, limit=80)
        except Exception as e:
            log.warning("FTS search failed: %s", e)
            return []

    def _search_sparse(
        self, q_sparse: Dict[str, float], thread: Optional[str]
    ) -> List[Tuple[int, float]]:
        """Sparse vector similarity search across base + delta."""
        results: List[Tuple[int, float]] = []

        for db in (self._base, self._delta):
            try:
                if thread:
                    eids = db.vec_candidates_by_thread(thread, limit=2000)
                else:
                    eids = db.vec_candidates_recent(limit=2000)

                if eids:
                    scores = db.vec_similarity_sparse(q_sparse, eids)
                    results.extend(scores.items())
            except Exception as e:
                log.warning("Sparse search failed on %s: %s", db, e)

        # Sort and deduplicate (keep highest score per event_id)
        best: Dict[int, float] = {}
        for eid, score in results:
            if eid not in best or score > best[eid]:
                best[eid] = score

        return sorted(best.items(), key=lambda x: x[1], reverse=True)

    def _tier2_rerank(
        self, query: str, candidates: List[CandidateFeatures]
    ) -> List[CandidateFeatures]:
        """Apply Tier 2 dense reranking."""
        try:
            import numpy as np

            q_dense = self._embedder.dense(query)
            if q_dense is None:
                return candidates

            # Batch-load dense vectors from base + delta
            eids = [c.event_id for c in candidates]
            dense_vecs: Dict[int, Any] = {}

            for db in (self._base, self._delta):
                batch = db.vec_get_dense_batch(eids)
                for eid, blob in batch.items():
                    if blob:
                        dense_vecs[eid] = bytes_to_dense(blob)

            if not dense_vecs:
                return candidates

            return self._tier2.score(candidates, q_dense, dense_vecs)

        except Exception as e:
            log.warning("Tier 2 reranking failed: %s", e)
            return candidates
