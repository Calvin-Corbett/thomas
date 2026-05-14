from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from agent_memory.indexing.derived_db import DerivedDB
from agent_memory.vector.embedder import EmbedderConfig, HashEmbedder


@dataclass
class VectorConfig:
    thread_candidate_limit: int = 2000
    global_candidate_limit: int = 2000

class VectorIndex:
    def __init__(self, db: DerivedDB, embedder: HashEmbedder | None = None, cfg: VectorConfig = VectorConfig()):
        self.db = db
        self.embedder = embedder or HashEmbedder(EmbedderConfig())
        self.cfg = cfg

    def upsert_event(self, event_id: int, thread: str, ts_utc: int, etype: str, text: str):
        vec = self.embedder.embed(text)
        self.db.vec_upsert(event_id, thread, ts_utc, etype, vec)

    def query(self, text: str, candidates: list[int]) -> dict[int, float]:
        qv = self.embedder.embed(text)
        return self.db.vec_similarity(qv, candidates)
