"""Reranking system for memory retrieval candidates.

Two-tier reranking:
- Tier 1: Feature-based scoring (fast, always available)
- Tier 2: Dense cosine similarity reranking (when embeddings available)
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from thomas.memory.store import EventRow

# ---------------------------------------------------------------------------
# Candidate features
# ---------------------------------------------------------------------------


@dataclass
class CandidateFeatures:
    """Feature vector for a retrieval candidate, used by Tier 1 reranker."""

    event_id: int
    event: Optional[EventRow] = None

    # Retrieval scores (from different sources)
    fts_score: float = 0.0        # BM25 full-text search score
    sparse_score: float = 0.0     # Sparse vector cosine similarity
    dense_score: float = 0.0      # Dense vector cosine similarity
    graph_score: float = 0.0      # Graph relevance score

    # Temporal features
    recency: float = 0.0          # 0.0 = oldest, 1.0 = most recent
    age_hours: float = 0.0        # Age in hours

    # Content features
    text_length: int = 0          # Length of the event text
    etype_weight: float = 1.0     # Weight multiplier by event type

    # Combined score (set by reranker)
    final_score: float = 0.0


# Event type weights — more important types score higher
_ETYPE_WEIGHTS: Dict[str, float] = {
    "user_message": 1.2,
    "assistant_response": 1.0,
    "tool_result": 0.6,
    "tool_call": 0.4,
    "system": 0.8,
    "summary": 1.5,
    "pin": 2.0,
    "fact": 1.8,
}

# Tier 1 feature weights — tuned for coding assistant use
_TIER1_WEIGHTS: Dict[str, float] = {
    "fts_score": 0.30,
    "sparse_score": 0.15,
    "dense_score": 0.25,
    "graph_score": 0.10,
    "recency": 0.15,
    "etype_weight": 0.05,
}


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------


def compute_features(
    candidates: List[CandidateFeatures],
    now_ts: Optional[int] = None,
) -> None:
    """Compute temporal and content features for all candidates in-place."""
    if not candidates:
        return

    now = now_ts or int(time.time())
    max_age = 1.0  # Avoid division by zero

    # First pass: compute ages
    for c in candidates:
        if c.event is not None:
            c.age_hours = max(0, (now - c.event.ts_utc)) / 3600.0
            c.text_length = len(c.event.text)
            c.etype_weight = _ETYPE_WEIGHTS.get(c.event.etype, 1.0)
            if c.age_hours > max_age:
                max_age = c.age_hours

    # Second pass: normalize recency
    for c in candidates:
        if max_age > 0:
            c.recency = 1.0 - (c.age_hours / max_age)
        else:
            c.recency = 1.0


# ---------------------------------------------------------------------------
# Tier 1 — Feature-based reranker (always available)
# ---------------------------------------------------------------------------


class Tier1Reranker:
    """Fast feature-based reranker using weighted linear combination.

    Always available, no ML dependencies. Uses the feature weights
    defined above to combine retrieval scores, recency, and type weights.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self._weights = weights or _TIER1_WEIGHTS

    def score(self, candidates: List[CandidateFeatures]) -> List[CandidateFeatures]:
        """Score and sort candidates by weighted feature combination.

        Modifies candidates in-place and returns sorted (highest first).
        """
        compute_features(candidates)

        for c in candidates:
            c.final_score = (
                self._weights.get("fts_score", 0) * c.fts_score
                + self._weights.get("sparse_score", 0) * c.sparse_score
                + self._weights.get("dense_score", 0) * c.dense_score
                + self._weights.get("graph_score", 0) * c.graph_score
                + self._weights.get("recency", 0) * c.recency
                + self._weights.get("etype_weight", 0) * (c.etype_weight / 2.0)
            )

        candidates.sort(key=lambda c: c.final_score, reverse=True)
        return candidates


# ---------------------------------------------------------------------------
# Tier 2 — Dense reranker (when embeddings available)
# ---------------------------------------------------------------------------


class Tier2Reranker:
    """Dense embedding reranker using cosine similarity.

    Requires sentence-transformers. Takes the top-K from Tier 1
    and rescores using dense vector similarity.
    """

    def score(
        self,
        candidates: List[CandidateFeatures],
        query_vec: np.ndarray,
        dense_vecs: Dict[int, np.ndarray],
        weight: float = 0.4,
    ) -> List[CandidateFeatures]:
        """Rescore candidates using dense similarity.

        Blends dense_score with existing final_score:
            new_score = (1 - weight) * tier1_score + weight * dense_score

        Args:
            candidates: Pre-scored by Tier 1
            query_vec: Dense query embedding (dim,)
            dense_vecs: {event_id: dense_vector} for candidates
            weight: Blend weight for dense score (0-1)

        Returns:
            Rescored and re-sorted candidates
        """
        for c in candidates:
            if c.event_id in dense_vecs:
                dvec = dense_vecs[c.event_id]
                # Cosine similarity (both normalized)
                c.dense_score = float(np.dot(query_vec, dvec))
                c.final_score = (1 - weight) * c.final_score + weight * c.dense_score

        candidates.sort(key=lambda c: c.final_score, reverse=True)
        return candidates


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion (RRF) — for merging retrieval lists
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    *ranked_lists: List[Tuple[int, float]],
    k: int = 60,
) -> Dict[int, float]:
    """Merge multiple ranked lists using Reciprocal Rank Fusion.

    Each list is [(event_id, score)] sorted by score descending.
    Returns {event_id: rrf_score} merged from all lists.

    RRF score = sum over lists of 1 / (k + rank_in_list)
    where k=60 is standard.
    """
    fused: Dict[int, float] = {}

    for ranked in ranked_lists:
        for rank, (eid, _score) in enumerate(ranked):
            rrf = 1.0 / (k + rank + 1)  # +1 because rank is 0-indexed
            fused[eid] = fused.get(eid, 0.0) + rrf

    return fused
