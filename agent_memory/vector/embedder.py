from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List
from collections.abc import Iterable

_WORD = re.compile(r"[a-zA-Z0-9_]+")

@dataclass
class EmbedderConfig:
    dims: int = 2**16  # feature hashing buckets
    ngram_max: int = 2

class HashEmbedder:
    """Stateless embedding (hashing). Good enough to make the engine fully functional today.
    Swap with a real embedding model by implementing the same interface."""

    def __init__(self, cfg: EmbedderConfig = EmbedderConfig()):
        self.cfg = cfg

    def embed(self, text: str) -> dict[str, float]:
        tokens = [t.lower() for t in _WORD.findall(text)]
        feats: dict[int, float] = {}
        dims = self.cfg.dims
        # unigrams
        for tok in tokens:
            i = (hash(("u", tok)) % dims)
            feats[i] = feats.get(i, 0.0) + 1.0
        # bigrams
        if self.cfg.ngram_max >= 2:
            for a, b in zip(tokens, tokens[1:]):
                i = (hash(("b", a, b)) % dims)
                feats[i] = feats.get(i, 0.0) + 1.0
        # return as str keys to keep JSON compact + stable
        return {str(k): float(v) for k, v in feats.items()}

    def embed_many(self, texts: list[str]) -> list[dict[str, float]]:
        return [self.embed(t) for t in texts]
