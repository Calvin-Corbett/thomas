from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

try:
    import numpy as np
    from sklearn.linear_model import SGDClassifier
except Exception as e:
    raise RuntimeError("Training requires optional dependencies. Install with: pip install .[train]") from e

from agent_memory.storage.meta_db import MetaDB
from agent_memory.rerank.tier2 import Tier2Reranker
from agent_memory.rerank.features import CandidateFeatures

@dataclass
class TrainConfig:
    max_traces: int = 4000
    max_candidates_per_trace: int = 40
    lr: float = 0.01
    epochs: int = 4

def _features_to_array(feats: CandidateFeatures, keys: List[str]) -> np.ndarray:
    d = feats.to_dict()
    return np.array([d.get(k, 0.0) for k in keys], dtype=np.float32)

def train_linear_from_traces(meta: MetaDB, tier2: Tier2Reranker, cfg: TrainConfig = TrainConfig()) -> Dict[str, float]:
    # Build dataset: positives are final_selected IDs; negatives are top candidates not selected.
    keys = ["fts", "vec", "graph", "recency", "etype_bonus", "thread_match", "pinned", "prior_useful"]
    X: List[np.ndarray] = []
    y: List[int] = []

    n = 0
    for _, _, _, _, trace in meta.trace_iter(limit=cfg.max_traces):
        cands = trace.get("candidates", [])
        selected = set(trace.get("selected", []))
        # Keep bounded
        cands = cands[: cfg.max_candidates_per_trace]
        for c in cands:
            f = CandidateFeatures(
                eid=int(c["eid"]),
                fts=float(c.get("fts", 0.0)),
                vec=float(c.get("vec", 0.0)),
                graph=float(c.get("graph", 0.0)),
                recency_s=float(c.get("recency", 0.0)),
                etype_bonus=float(c.get("etype_bonus", 0.0)),
                thread_match=float(c.get("thread_match", 1.0)),
                pinned_bonus=float(c.get("pinned", 0.0)),
                prior_useful=float(c.get("prior_useful", 0.0)),
            )
            X.append(_features_to_array(f, keys))
            y.append(1 if f.eid in selected else 0)
        n += 1
        if n >= cfg.max_traces:
            break

    if not X:
        return {}

    Xmat = np.stack(X, axis=0)
    yarr = np.array(y, dtype=np.int32)

    clf = SGDClassifier(loss="log_loss", alpha=1e-4, learning_rate="optimal", max_iter=2000, tol=1e-3)
    clf.fit(Xmat, yarr)

    weights = {k: float(w) for k, w in zip(keys, clf.coef_[0].tolist())}
    bias = float(clf.intercept_[0])
    tier2.weights = weights
    tier2.bias = bias
    tier2.enabled = True
    tier2.save()
    return weights
