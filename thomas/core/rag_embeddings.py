"""Embedding model management and vector operations for RAG index.

Provides embedding generation, model loading, and vector-based search support.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _make_chroma_collection(persist_dir: str, collection_name: str):
    """Create or get a Chroma collection for vector storage.

    Args:
        persist_dir: Directory path for Chroma persistence
        collection_name: Name of the collection

    Returns:
        Tuple of (chromadb.PersistentClient, collection)

    Raises:
        RuntimeError: If chromadb is not installed
    """
    try:
        import chromadb
    except ImportError as e:
        raise RuntimeError("chromadb is required. Install: pip install chromadb") from e

    client = chromadb.PersistentClient(path=persist_dir)
    col = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    return client, col


def _load_embedder(model_name: str):
    """Load a SentenceTransformer embedding model.

    Args:
        model_name: Model identifier (e.g., 'all-MiniLM-L6-v2')

    Returns:
        Loaded SentenceTransformer model instance

    Raises:
        RuntimeError: If sentence-transformers is not installed
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError("sentence-transformers required. Install: pip install sentence-transformers") from e
    return SentenceTransformer(model_name)


def _rrf_fuse(a: list[dict[str, Any]], b: list[dict[str, Any]], k0: int = 60) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion: fuse two ranked lists by combining scores.

    This is a robust fusion technique that doesn't require normalized scores.
    Items that appear in both lists get boosted scores.

    Args:
        a: First ranked list of results
        b: Second ranked list of results
        k0: Constant for RRF formula (default 60)

    Returns:
        Fused and re-ranked list of results
    """
    fused: dict[str, dict[str, Any]] = {}

    def add(lst: list[dict[str, Any]], weight: float) -> None:
        for r, item in enumerate(lst, start=1):
            key = item.get("id") or item.get("file") or f"r{r}"
            contrib = weight * (1.0 / (k0 + r))
            if key not in fused:
                fused[key] = dict(item)
                fused[key]["score"] = float(contrib)
            else:
                fused[key]["score"] = float(fused[key].get("score", 0.0) + contrib)

    add(a, 1.0)
    add(b, 1.0)

    out = list(fused.values())
    out.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return out
