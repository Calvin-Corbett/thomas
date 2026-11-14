"""The commit a checkout is on, read from its ``.git`` files instead of by running git.

``git rev-parse HEAD`` costs a process start, and on this machine it was asked for on every health check and every
reload check: 448 calls at 1.4 s each in one server run (2026-11-06), enough to hold the thread pool while pages were
loading. The answer is two small files, so this reads them and remembers the result until one of them changes.

Anything unusual (a detached or unreadable HEAD, a missing ref, a worktree layout this does not understand) returns
``None`` and the caller asks git as before, so this can only ever be faster, never different.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

_lock = threading.Lock()
_cache: dict[str, tuple[tuple[tuple[str, int, int], ...], str]] = {}


def _stamp(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
        return (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return (str(path), 0, -1)


def _git_dir(root: Path) -> Path | None:
    dot = root / ".git"
    if dot.is_dir():
        return dot
    try:  # a linked worktree: ".git" is a file saying where its own folder is
        text = dot.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    target = Path(text.split(":", 1)[1].strip())
    return target if target.is_absolute() else (root / target).resolve()


def _common_dir(git_dir: Path) -> Path:
    try:
        text = (git_dir / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        return git_dir
    return Path(text) if os.path.isabs(text) else (git_dir / text).resolve()


def _is_sha(value: str) -> bool:
    return len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def _ref_value(common: Path, git_dir: Path, ref: str) -> str | None:
    for base in (git_dir, common):
        try:
            value = (base / ref).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if _is_sha(value):
            return value
    try:
        packed = (common / "packed-refs").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in packed.splitlines():
        if line.endswith(" " + ref) and not line.startswith(("#", "^")):
            return line.split(" ", 1)[0]
    return None


def head_sha(root: str | Path) -> str | None:
    """The full 40-character commit HEAD points at in ``root``, or ``None`` when this cannot say."""
    root = Path(root)
    git_dir = _git_dir(root)
    if git_dir is None:
        return None
    common = _common_dir(git_dir)
    head_file = git_dir / "HEAD"
    try:
        head = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    files = [head_file]
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        files += [git_dir / ref, common / ref, common / "packed-refs"]
    stamps = tuple(_stamp(path) for path in files)
    key = str(git_dir)
    with _lock:
        hit = _cache.get(key)
    if hit and hit[0] == stamps:
        return hit[1]
    if head.startswith("ref:"):
        sha = _ref_value(common, git_dir, head.split(":", 1)[1].strip())
    elif _is_sha(head):
        sha = head
    else:
        sha = None
    if sha is None:
        return None
    with _lock:
        _cache[key] = (stamps, sha)
    return sha
