from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional
import math
import time

@dataclass
class CandidateFeatures:
    eid: int
    fts: float = 0.0
    vec: float = 0.0
    graph: float = 0.0
    recency_s: float = 0.0
    etype_bonus: float = 0.0
    thread_match: float = 1.0
    pinned_bonus: float = 0.0
    prior_useful: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "fts": float(self.fts),
            "vec": float(self.vec),
            "graph": float(self.graph),
            "recency": float(self.recency_s),
            "etype_bonus": float(self.etype_bonus),
            "thread_match": float(self.thread_match),
            "pinned": float(self.pinned_bonus),
            "prior_useful": float(self.prior_useful),
        }

def recency_feature(now_ts: int, event_ts: int) -> float:
    # Higher is better. Smooth decay with half-life ~7 days.
    dt = max(0, now_ts - event_ts)
    half = 7 * 24 * 3600
    return float(math.exp(-dt / half))
