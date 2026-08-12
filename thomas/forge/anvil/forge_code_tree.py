"""Bounded, metadata-only file tree for a selected Forge Code repository."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any


class ForgeCodeTreeError(ValueError):
    """Raised when a tree path is invalid or escapes the selected repository."""


_HIDDEN_INTERNAL = {".git", ".thomas", "__pycache__", "node_modules"}


def _relative_path(value: str | None) -> PurePosixPath:
    normalized = str(value or "").strip().replace("\\", "/")
    relative = PurePosixPath(normalized or ".")
    if relative.is_absolute() or any(part in {"..", ""} for part in relative.parts):
        raise ForgeCodeTreeError("tree path must stay inside the selected project")
    return relative


def list_project_tree(
    project_root: str | Path,
    relative_path: str | None = "",
    *,
    limit: int = 250,
) -> dict[str, Any]:
    """List one directory level without reading file contents or following links."""

    root = Path(project_root).resolve(strict=True)
    relative = _relative_path(relative_path)
    try:
        target = (root / Path(*relative.parts)).resolve(strict=True)
    except OSError as exc:
        raise ForgeCodeTreeError("tree path was not found") from exc
    if not target.is_relative_to(root):
        raise ForgeCodeTreeError("tree path escapes the selected project")
    if not target.is_dir():
        raise ForgeCodeTreeError("tree path must identify a directory")

    safe_limit = max(1, min(int(limit), 500))
    rows: list[dict[str, Any]] = []
    try:
        children = sorted(
            target.iterdir(),
            key=lambda item: (item.is_symlink() or not item.is_dir(), item.name.lower()),
        )
    except OSError as exc:
        raise ForgeCodeTreeError("tree directory could not be read") from exc
    truncated = len(children) > safe_limit
    for child in children[:safe_limit]:
        if child.name in _HIDDEN_INTERNAL:
            continue
        rel = child.relative_to(root).as_posix()
        if child.is_symlink():
            kind = "symlink"
            size = None
        elif child.is_dir():
            kind = "directory"
            size = None
        elif child.is_file():
            kind = "file"
            try:
                size = child.stat().st_size
            except OSError:
                size = None
        else:
            continue
        rows.append({"name": child.name, "path": rel, "kind": kind, "size": size})

    display_path = "" if relative == PurePosixPath(".") else relative.as_posix()
    return {
        "project_root": str(root),
        "path": display_path,
        "entries": rows,
        "truncated": truncated,
    }


def read_project_file(
    project_root: str | Path,
    relative_path: str,
    *,
    max_bytes: int = 200_000,
) -> dict[str, Any]:
    """Read one bounded UTF-8 text file from the selected repository."""

    root = Path(project_root).resolve(strict=True)
    relative = _relative_path(relative_path)
    try:
        target = (root / Path(*relative.parts)).resolve(strict=True)
    except OSError as exc:
        raise ForgeCodeTreeError("file path was not found") from exc
    if not target.is_relative_to(root) or not target.is_file() or target.is_symlink():
        raise ForgeCodeTreeError("file path must identify a regular file inside the selected project")
    safe_limit = max(1_024, min(int(max_bytes), 500_000))
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise ForgeCodeTreeError("file could not be read") from exc
    if len(raw) > safe_limit:
        raise ForgeCodeTreeError(f"file exceeds the {safe_limit}-byte preview limit")
    if b"\x00" in raw:
        raise ForgeCodeTreeError("binary files cannot be previewed as text")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ForgeCodeTreeError("file is not valid UTF-8 text") from exc
    return {
        "project_root": str(root),
        "path": target.relative_to(root).as_posix(),
        "size": len(raw),
        "content": content,
    }
