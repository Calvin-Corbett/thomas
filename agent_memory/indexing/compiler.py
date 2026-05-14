from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from agent_memory.graph.store import GraphStore
from agent_memory.indexing.derived_db import DerivedDB
from agent_memory.indexing.index_manager import IndexManager
from agent_memory.storage.filelock import file_lock
from agent_memory.storage.meta_db import MetaDB
from agent_memory.storage.sqlite_log import ImmortalLog
from agent_memory.summarize.extractive import SummarizeConfig, summarize
from agent_memory.vector.index import VectorIndex


@dataclass
class CompilerConfig:
    lock_timeout_s: float = 25.0
    build_name_prefix: str = "build"
    weekly_rollup_events: int = 350

class Compiler:
    def __init__(self, root: Path, log: ImmortalLog, meta: MetaDB, idx: IndexManager, cfg: CompilerConfig = CompilerConfig()):
        self.root = root
        self.log = log
        self.meta = meta
        self.idx = idx
        self.cfg = cfg
        self.swap_lock = str(root / "indices" / "SWAP.lock")

    def _active_base_path(self) -> Path:
        active = self.idx.get_active().active_build
        return self.idx.builds_dir / active / "derived_base.db"

    def _delta_path(self) -> Path:
        return self.idx.indices_dir / "delta" / "derived_delta.db"

    def ensure_delta(self) -> DerivedDB:
        p = self._delta_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        return DerivedDB(p)

    def ingest_delta_event(self, event_id: int) -> None:
        # Update delta indices on hot path.
        ddb = self.ensure_delta()
        try:
            ev = self.log.get_event(event_id)
            if not ev:
                return
            vec = VectorIndex(ddb)
            vec.upsert_event(ev.id, ev.thread, ev.ts_utc, ev.etype, ev.text)
            graph = GraphStore(ddb)
            graph.ingest_event(ev.id, ev.text, ev.ts_utc, ev.thread, user_asserted=False)

            # light rollup cache (thread weekly)
            recents = self.log.recent_events(ev.thread, limit=80)
            roll = summarize([e.text for e in recents], SummarizeConfig(max_sentences=6, max_chars=900))
            ddb.rollup_set(f"thread:{ev.thread}:weekly", roll, meta={"source": "delta"})
            ddb.commit()
        finally:
            ddb.close()

    def mini_compact(self) -> None:
        # Merge delta into current base build (cheap path): rebuild base from base+delta file-by-file by copying tables.
        # For simplicity (and safety), we just run nightly compiler if needed.
        self.nightly()

    def nightly(self) -> str:
        # Build new base indices in a fresh build folder, then swap ACTIVE pointer.
        with file_lock(self.swap_lock, timeout_s=self.cfg.lock_timeout_s):
            ts = int(time.time())
            build_name = f"{self.cfg.build_name_prefix}_{ts}"
            bdir = self.idx.new_build_dir(build_name)
            base_db_path = bdir / "derived_base.db"
            base_db = DerivedDB(base_db_path)
            vec = VectorIndex(base_db)
            graph = GraphStore(base_db)

            # Rebuild from immortal log
            for ev in self.log.iter_events():
                vec.upsert_event(ev.id, ev.thread, ev.ts_utc, ev.etype, ev.text)
                graph.ingest_event(ev.id, ev.text, ev.ts_utc, ev.thread, user_asserted=False)

            # Weekly rollups per thread
            # naive: pick last N events per thread from log; for large logs, optimize later
            threads = {}
            for ev in self.log.iter_events():
                threads.setdefault(ev.thread, []).append(ev.text)
                if len(threads[ev.thread]) > self.cfg.weekly_rollup_events:
                    threads[ev.thread] = threads[ev.thread][-self.cfg.weekly_rollup_events:]
            for th, texts in threads.items():
                base_db.rollup_set(f"thread:{th}:weekly", summarize(texts, SummarizeConfig(max_sentences=7, max_chars=1200)), meta={"source": "nightly"})
            base_db.commit()
            base_db.close()

            # Atomic swap ACTIVE pointer
            self.idx.set_active(build_name)

            # Clear delta (recreate)
            delta_path = self._delta_path()
            if delta_path.exists():
                try:
                    os.remove(delta_path)
                except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError):
                    # Windows locking: rename instead of delete
                    try:
                        os.replace(str(delta_path), str(delta_path.with_suffix(f".old.{ts}")))
                    except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError):
                        pass
            # recreate empty delta db
            _ = DerivedDB(delta_path)
            _.close()

            return build_name
