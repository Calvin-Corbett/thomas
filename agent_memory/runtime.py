from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from agent_memory.config import AppPaths
from agent_memory.storage.sqlite_log import ImmortalLog
from agent_memory.storage.meta_db import MetaDB
from agent_memory.storage.blob_store import BlobStore
from agent_memory.indexing.index_manager import IndexManager
from agent_memory.indexing.derived_db import DerivedDB
from agent_memory.indexing.compiler import Compiler

@dataclass
class Runtime:
    paths: AppPaths
    log: ImmortalLog
    meta: MetaDB
    blobs: BlobStore
    idx: IndexManager
    compiler: Compiler

    def close(self):
        self.log.close()
        self.meta.close()

def init_runtime(root: Path) -> Runtime:
    paths = AppPaths.from_root(root)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.blobs_dir.mkdir(parents=True, exist_ok=True)
    paths.indices_dir.mkdir(parents=True, exist_ok=True)
    paths.builds_dir.mkdir(parents=True, exist_ok=True)
    paths.delta_dir.mkdir(parents=True, exist_ok=True)

    log = ImmortalLog(paths.data_dir / "memory.db")
    meta = MetaDB(paths.data_dir / "meta.db")
    blobs = BlobStore(paths.blobs_dir)
    idx = IndexManager(paths.indices_dir)
    idx.ensure_bootstrap()

    # Ensure bootstrap derived db exists
    bootstrap_db = paths.builds_dir / "bootstrap" / "derived_base.db"
    if not bootstrap_db.exists():
        db = DerivedDB(bootstrap_db)
        db.close()

    # Ensure delta exists
    delta_db = paths.delta_dir / "derived_delta.db"
    if not delta_db.exists():
        db = DerivedDB(delta_db)
        db.close()

    compiler = Compiler(root=paths.root, log=log, meta=meta, idx=idx)
    return Runtime(paths=paths, log=log, meta=meta, blobs=blobs, idx=idx, compiler=compiler)

def open_active_indices(rt: Runtime) -> Tuple[DerivedDB, DerivedDB]:
    active = rt.idx.get_active().active_build
    base_path = rt.paths.builds_dir / active / "derived_base.db"
    delta_path = rt.paths.delta_dir / "derived_delta.db"
    base_db = DerivedDB(base_path)
    delta_db = DerivedDB(delta_path)
    return base_db, delta_db
