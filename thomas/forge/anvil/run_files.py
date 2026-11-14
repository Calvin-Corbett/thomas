"""Where a Build run's files live in a catalog: light, so a plugin can read a run's transcript without its runtime."""

from __future__ import annotations

import hashlib
from pathlib import Path


def agent_dir(root: Path) -> Path:
    d = root / ".thomas" / "evolve" / "agent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def transcript_path(root: Path, run_id: str = "") -> Path:
    suffix = f"-{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:16]}" if run_id else ""
    return agent_dir(root) / f"transcript{suffix}.txt"
