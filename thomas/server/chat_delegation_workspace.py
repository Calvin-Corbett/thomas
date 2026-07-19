"""Workspace snapshots used to verify delegated worker deliverables."""

from __future__ import annotations

import logging
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)


def ensure_task_workspace(execution_id: str) -> Path:
    """Return a per-task workspace outside the source repo when possible."""
    safe_id = "".join(ch for ch in str(execution_id or "") if ch.isalnum() or ch in "-_") or "task"
    base = Path.home() / ".thomas" / "workspaces" / safe_id
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = (ROOT / "runtime" / "workspaces" / safe_id).resolve()
        base.mkdir(parents=True, exist_ok=True)
    return base


def snapshot_workspace_files(work_dir: Path | None, *, limit: int = 24) -> list[str]:
    """List real, non-hidden deliverable files relative to a worker workspace."""

    if work_dir is None:
        return []
    base = Path(work_dir)
    if not base.exists() or not base.is_dir():
        return []
    files: list[str] = []
    try:
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base)
            if any(part.startswith(".") for part in rel.parts):
                continue
            files.append(rel.as_posix())
            if len(files) >= limit:
                break
    except (OSError, RuntimeError, ValueError) as exc:
        log.debug("workspace snapshot error in %s: %s", work_dir, exc)
    return files


def workspace_mtimes(
    work_dir: Path | None,
    *,
    ignored_prefixes: tuple[str, ...] = (),
    ignored_parts: frozenset[str] = frozenset(),
) -> dict[str, tuple[int, int]]:
    """Map workspace files to mtime and size while honoring ignored paths."""

    out: dict[str, tuple[int, int]] = {}
    if work_dir is None:
        return out
    base = Path(work_dir)
    if not base.exists() or not base.is_dir():
        return out
    normalized_prefixes = tuple(str(prefix or "").replace("\\", "/").lstrip("/") for prefix in ignored_prefixes)

    def ignored_rel(rel: str) -> bool:
        rel = rel.replace("\\", "/").lstrip("/")
        if not rel:
            return False
        if any(part in ignored_parts for part in rel.split("/")):
            return True
        return any(rel.startswith(prefix) for prefix in normalized_prefixes if prefix)

    try:
        for root, dirs, files in os.walk(base):
            root_path = Path(root)
            try:
                rel_root = "" if root_path == base else root_path.relative_to(base).as_posix().rstrip("/") + "/"
            except ValueError:
                continue
            dirs[:] = [
                dirname
                for dirname in dirs
                if not dirname.startswith(".")
                and dirname not in ignored_parts
                and not ignored_rel(rel_root + dirname + "/")
            ]
            for filename in files:
                if filename.startswith("."):
                    continue
                path = root_path / filename
                rel = path.relative_to(base)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                rel_posix = rel.as_posix()
                if ignored_rel(rel_posix):
                    continue
                try:
                    stat = path.stat()
                    out[rel_posix] = (stat.st_mtime_ns, stat.st_size)
                except OSError:
                    continue
    except (OSError, RuntimeError, ValueError) as exc:
        log.debug("workspace mtimes walk error in %s: %s", work_dir, exc)
    return out


def files_changed_since(
    work_dir: Path | None,
    baseline: dict[str, tuple[int, int]],
    *,
    limit: int = 24,
) -> list[str]:
    """Return files created or modified since a workspace baseline."""

    after = workspace_mtimes(work_dir)
    return sorted(filename for filename, metadata in after.items() if baseline.get(filename) != metadata)[:limit]
