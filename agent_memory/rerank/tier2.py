from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_memory.rerank.features import CandidateFeatures


@dataclass
class Tier2Config:
    model_path: str = "tier2_model.json"
    enabled: bool = False

class Tier2Reranker:
    """Learned reranker.
    Default implementation: linear weights learned from traces (fast, inspectable).
    If catboost is available, you can switch to it later without changing the API.
    """
    def __init__(self, cfg: Tier2Config, root_dir: Path):
        self.cfg = cfg
        self.root_dir = root_dir
        self.model_file = root_dir / cfg.model_path
        self.weights: dict[str, float] = {}
        self.bias: float = 0.0
        self.enabled = cfg.enabled and self.model_file.exists()
        if self.model_file.exists():
            self._load()

    def _load(self):
        data = json.loads(self.model_file.read_text(encoding="utf-8"))
        self.weights = {k: float(v) for k, v in data.get("weights", {}).items()}
        self.bias = float(data.get("bias", 0.0))

    def save(self):
        self.model_file.parent.mkdir(parents=True, exist_ok=True)
        self.model_file.write_text(json.dumps({"weights": self.weights, "bias": self.bias}, indent=2), encoding="utf-8")

    def score(self, f: CandidateFeatures) -> float:
        if not self.enabled or not self.weights:
            return 0.0
        x = f.to_dict()
        s = self.bias
        for k, v in x.items():
            s += self.weights.get(k, 0.0) * v
        return float(s)

    def rank(self, feats: list[CandidateFeatures]) -> list[tuple[int, float]]:
        scored = [(f.eid, self.score(f)) for f in feats]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
