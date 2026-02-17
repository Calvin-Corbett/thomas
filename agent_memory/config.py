from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class AppPaths:
    root: Path
    data_dir: Path
    blobs_dir: Path
    indices_dir: Path
    builds_dir: Path
    delta_dir: Path

    @staticmethod
    def from_root(root: Path) -> "AppPaths":
        root = root.resolve()
        data_dir = root / "data"
        blobs_dir = root / "blobs"
        indices_dir = root / "indices"
        builds_dir = indices_dir / "builds"
        delta_dir = indices_dir / "delta"
        return AppPaths(root=root, data_dir=data_dir, blobs_dir=blobs_dir, indices_dir=indices_dir, builds_dir=builds_dir, delta_dir=delta_dir)
