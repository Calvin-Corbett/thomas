"""Embedding engine with sentence-transformers + HashEmbedder fallback.

Provides both dense (sentence-transformers on GPU) and sparse (feature hashing)
embeddings. Loads model on demand to manage VRAM on user's RTX 3080.
"""

from __future__ import annotations

import hashlib
import logging

import numpy as np

from thomas.core.config import EmbedConfig

log = logging.getLogger(__name__)

# Try importing sentence-transformers at module level for availability check
try:
    from sentence_transformers import SentenceTransformer

    _HAS_SBERT = True
except ImportError:
    _HAS_SBERT = False


# ---------------------------------------------------------------------------
# Sparse fallback — always available
# ---------------------------------------------------------------------------


class HashEmbedder:
    """Sparse feature-hashing embedder. No GPU, no dependencies.

    Produces a Dict[str, float] where keys are hashed n-gram features.
    Used when sentence-transformers is not installed or for sparse retrieval.
    """

    def __init__(self, n_features: int = 4096, ngram_range: tuple = (1, 2)):
        self._n_features = n_features
        self._ngram_min = ngram_range[0]
        self._ngram_max = ngram_range[1]

    def embed_text(self, text: str) -> dict[str, float]:
        """Produce a sparse vector from text via feature hashing."""
        tokens = text.lower().split()
        vec: dict[str, float] = {}

        for n in range(self._ngram_min, self._ngram_max + 1):
            for i in range(len(tokens) - n + 1):
                gram = " ".join(tokens[i : i + n])
                # Feature hashing is not a cryptographic use case.
                # Keep MD5 output stable for backwards-compatible bucket mapping.
                h = hashlib.md5(gram.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
                bucket = f"h{int(h, 16) % self._n_features}"
                vec[bucket] = vec.get(bucket, 0.0) + 1.0

        # L2 normalize
        norm = sum(v * v for v in vec.values()) ** 0.5
        if norm > 0:
            vec = {k: v / norm for k, v in vec.items()}
        return vec

    def embed_batch(self, texts: list[str]) -> list[dict[str, float]]:
        return [self.embed_text(t) for t in texts]


# ---------------------------------------------------------------------------
# Dense embedder — sentence-transformers
# ---------------------------------------------------------------------------


class DenseEmbedder:
    """Dense embedder using sentence-transformers with load-on-demand.

    The model is loaded lazily on first call to save VRAM when not needed.
    Embeddings are returned as numpy arrays and can be serialized to bytes
    for SQLite BLOB storage.
    """

    def __init__(self, config: EmbedConfig):
        self._config = config
        self._model: SentenceTransformer | None = None  # type: ignore[name-defined]
        self._dim: int = 0

    @property
    def available(self) -> bool:
        return _HAS_SBERT

    @property
    def dim(self) -> int:
        if self._dim == 0:
            self._ensure_loaded()
        return self._dim

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if not _HAS_SBERT:
            raise RuntimeError("sentence-transformers not installed. Install with: pip install sentence-transformers")

        device = self._resolve_device()
        log.info("Loading embedding model: %s on %s", self._config.model, device)
        try:
            self._model = SentenceTransformer(self._config.model, device=device)
        except (RuntimeError, ValueError) as e:
            # If the user asked for CUDA but it's unavailable/misconfigured, fall back to CPU.
            if str(device).lower().startswith("cuda"):
                log.warning(
                    "Failed to load embedding model on %s (%s). Falling back to CPU.",
                    device,
                    e,
                )
                self._model = SentenceTransformer(self._config.model, device="cpu")
            else:
                raise
        # Probe dimension
        test = self._model.encode(["test"], convert_to_numpy=True)
        self._dim = test.shape[1]
        log.info("Embedding model loaded. dim=%d", self._dim)

    def _resolve_device(self) -> str:
        """Resolve config device string into an actual SentenceTransformer device."""
        raw = (self._config.device or "").strip()
        if raw.lower() != "auto":
            return raw or "cpu"
        try:
            import torch  # sentence-transformers depends on torch, but be defensive

            return "cuda" if torch.cuda.is_available() else "cpu"
        except (ImportError, RuntimeError):
            return "cpu"

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Encode texts to dense vectors. Returns (N, dim) float32 array."""
        self._ensure_loaded()
        if self._model is None:
            raise RuntimeError("Dense model failed to load")
        return self._model.encode(
            texts,
            batch_size=self._config.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    def embed_one(self, text: str) -> np.ndarray:
        """Encode a single text. Returns (dim,) float32 array."""
        return self.embed_texts([text])[0]

    def unload(self) -> None:
        """Free GPU memory by unloading the model."""
        if self._model is not None:
            del self._model
            self._model = None
            self._dim = 0
            log.info("Embedding model unloaded")
            # Try to free CUDA cache
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def dense_to_bytes(vec: np.ndarray) -> bytes:
    """Serialize a float32 numpy vector to bytes for SQLite BLOB storage."""
    return vec.astype(np.float32).tobytes()


def bytes_to_dense(data: bytes) -> np.ndarray:
    """Deserialize bytes back to a float32 numpy vector."""
    return np.frombuffer(data, dtype=np.float32)


def cosine_similarity_dense(query: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between query and candidate vectors.

    Args:
        query: (dim,) normalized float32 vector
        candidates: (N, dim) normalized float32 matrix

    Returns:
        (N,) float32 array of similarities
    """
    # Both should already be normalized, so dot product = cosine sim
    return candidates @ query


# ---------------------------------------------------------------------------
# Unified Embedder — facade
# ---------------------------------------------------------------------------


class Embedder:
    """Unified embedding facade: sparse always, dense when available.

    Usage:
        embedder = Embedder(config)
        sparse = embedder.sparse("hello world")
        if embedder.has_dense:
            dense_bytes = embedder.dense_bytes("hello world")
    """

    def __init__(self, config: EmbedConfig):
        self._config = config
        self._hash = HashEmbedder()
        self._dense: DenseEmbedder | None = None
        if _HAS_SBERT:
            self._dense = DenseEmbedder(config)

    @property
    def has_dense(self) -> bool:
        return self._dense is not None and self._dense.available

    @property
    def dense_dim(self) -> int:
        if self._dense is None:
            return 0
        return self._dense.dim

    def sparse(self, text: str) -> dict[str, float]:
        """Get sparse (hash) embedding for text."""
        return self._hash.embed_text(text)

    def sparse_batch(self, texts: list[str]) -> list[dict[str, float]]:
        """Get sparse embeddings for a batch of texts."""
        return self._hash.embed_batch(texts)

    def dense(self, text: str) -> np.ndarray | None:
        """Get dense embedding as numpy array, or None if unavailable."""
        if self._dense is None:
            return None
        return self._dense.embed_one(text)

    def dense_batch(self, texts: list[str]) -> np.ndarray | None:
        """Get dense embeddings as (N, dim) array, or None if unavailable."""
        if self._dense is None:
            return None
        return self._dense.embed_texts(texts)

    def dense_bytes(self, text: str) -> bytes | None:
        """Get dense embedding as bytes for SQLite BLOB, or None."""
        vec = self.dense(text)
        if vec is None:
            return None
        return dense_to_bytes(vec)

    def dense_bytes_batch(self, texts: list[str]) -> list[bytes | None]:
        """Get dense embeddings as bytes for a batch."""
        vecs = self.dense_batch(texts)
        if vecs is None:
            return [None] * len(texts)
        return [dense_to_bytes(v) for v in vecs]

    def unload_dense(self) -> None:
        """Free GPU memory from dense model."""
        if self._dense is not None:
            self._dense.unload()
