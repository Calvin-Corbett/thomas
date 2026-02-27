from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_memory.rerank.tier1 import Tier1Reranker
from agent_memory.rerank.tier2 import Tier2Config, Tier2Reranker
from agent_memory.retrieval.pipeline import RetrievalConfig, RetrievalPipeline
from agent_memory.runtime import init_runtime, open_active_indices


@dataclass
class AppConfig:
    tier2_enabled: bool = True


class AgentMemoryApp:
    def __init__(self, root: Path, cfg: AppConfig = AppConfig()):
        self.root = root
        self.cfg = cfg
        self.rt = init_runtime(root)
        self.tier1 = Tier1Reranker()
        self.tier2 = Tier2Reranker(Tier2Config(enabled=cfg.tier2_enabled), root_dir=self.rt.paths.root)

    def close(self):
        self.rt.close()

    def log_event(self, thread: str, etype: str, text: str, blob_text: str | None = None) -> int:
        blob_id = None
        if blob_text is not None:
            blob_id = self.rt.blobs.put_text(blob_text)
        eid = self.rt.log.add_event(thread=thread, etype=etype, text=text, metadata={}, blob_id=blob_id)
        self.rt.compiler.ingest_delta_event(eid)
        return eid

    def query(self, thread: str, mode: str, text: str) -> dict[str, Any]:
        if mode == "no_memory":
            trace = {
                "thread": thread,
                "mode": mode,
                "query": text,
                "selected": [],
                "candidates": [],
            }
            self.rt.meta.trace_add(thread=thread, mode=mode, query=text, trace=trace)
            return {"packed": "## L1\nMODE: no_memory", "selected": [], "trace": trace}

        base_db, delta_db = open_active_indices(self.rt)
        try:
            pipe = RetrievalPipeline(
                log=self.rt.log,
                meta=self.rt.meta,
                base_db=base_db,
                delta_db=delta_db,
                tier1=self.tier1,
                tier2=self.tier2,
                cfg=RetrievalConfig(),
            )
            return pipe.query(thread=thread, mode=mode, text=text)
        finally:
            base_db.close()
            delta_db.close()

    def nightly(self) -> str:
        return self.rt.compiler.nightly()

    def compact(self) -> str:
        self.rt.compiler.mini_compact()
        return "ok"
