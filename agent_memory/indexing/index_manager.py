from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from agent_memory.storage.filelock import file_lock

@dataclass
class ActiveIndex:
    active_build: str
    updated_ts_utc: int

class IndexManager:
    def __init__(self, indices_dir: Path):
        self.indices_dir = indices_dir
        self.builds_dir = indices_dir / "builds"
        self.active_path = indices_dir / "ACTIVE.json"
        self.lock_path = str(indices_dir / "ACTIVE.lock")
        self.builds_dir.mkdir(parents=True, exist_ok=True)

    def ensure_bootstrap(self) -> None:
        b = self.builds_dir / "bootstrap"
        b.mkdir(parents=True, exist_ok=True)
        derived = b / "derived_base.db"
        if not derived.exists():
            from agent_memory.indexing.derived_db import DerivedDB  # noqa: F401
            _ = DerivedDB(derived)
            _.close()
        if not self.active_path.exists():
            self.set_active("bootstrap")

    def get_active(self) -> ActiveIndex:
        if not self.active_path.exists():
            return ActiveIndex("bootstrap", int(time.time()))
        data = json.loads(self.active_path.read_text(encoding="utf-8"))
        return ActiveIndex(active_build=data["active_build"], updated_ts_utc=int(data["updated_ts_utc"]))

    def set_active(self, build_name: str) -> None:
        with file_lock(self.lock_path):
            tmp = self.active_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"active_build": build_name, "updated_ts_utc": int(time.time())}, indent=2), encoding="utf-8")
            os.replace(str(tmp), str(self.active_path))

    def new_build_dir(self, name: str) -> Path:
        p = self.builds_dir / name
        p.mkdir(parents=True, exist_ok=True)
        return p
