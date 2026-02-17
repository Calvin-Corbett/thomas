from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple

from agent_memory.rerank.features import CandidateFeatures

@dataclass
class Tier1Config:
    # Deterministic, sane defaults. Tier2 learns these.
    w_fts: float = 1.2
    w_vec: float = 1.0
    w_graph: float = 0.9
    w_recency: float = 0.6
    w_etype: float = 0.15
    w_thread: float = 0.2
    w_pinned: float = 0.4
    w_prior: float = 0.25
    epsilon: float = 0.03  # exploration noise

class Tier1Reranker:
    def __init__(self, cfg: Tier1Config = Tier1Config()):
        self.cfg = cfg

    def score(self, f: CandidateFeatures) -> float:
        c = self.cfg
        s = (
            c.w_fts * f.fts +
            c.w_vec * f.vec +
            c.w_graph * f.graph +
            c.w_recency * f.recency_s +
            c.w_etype * f.etype_bonus +
            c.w_thread * f.thread_match +
            c.w_pinned * f.pinned_bonus +
            c.w_prior * f.prior_useful
        )
        return float(s)

    def rank(self, feats: List[CandidateFeatures]) -> List[Tuple[int, float]]:
        scored = [(f.eid, self.score(f)) for f in feats]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
