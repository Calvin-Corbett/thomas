"""Remember a build's CHANGED FILES evidence until something git could see changes.

Opening a build asks for the diff of every file its run changed: one git status, then up to three git calls per file.
Measured on 2026-11-06 with four builds going: 17.8 s for a build with a handful of files, 14.9 s for one with a few
dozen, 39.3 s for the longest. The page asks again every time a build is opened, so a build nobody touched cost the
same 15 to 40 seconds every time.

A stored answer is used only when git cannot have a different one: every file the answer covers has the same size and
modification time, and the index, HEAD, the ref HEAD names and the ignore files are the same. Anything else, including a
folder this module cannot prove, goes to git as before. :mod:`thomas.forge.anvil.forge_code_git` keeps its rule of never
remembering anything; this module sits in front of it and is the only place that does.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_git

# Each entry can hold a few hundred KB of diff text; this keeps the whole store well under 30 MB.
MAX_ENTRIES = 24

_lock = threading.Lock()
_entries: OrderedDict[tuple, list[dict[str, Any]]] = OrderedDict()


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        found = path.stat()
    except OSError:
        return None
    return (found.st_mtime_ns, found.st_size)


def _git_dir(root: Path) -> Path | None:
    """The folder holding this checkout's index and HEAD; None when it cannot be read plainly."""
    dot = root / ".git"
    try:
        if dot.is_dir():
            return dot
        text = dot.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    target = Path(text[len("gitdir:") :].strip())
    target = target if target.is_absolute() else root / target
    return target if target.is_dir() else None


def evidence_key(root: str | Path, files: list[str] | None) -> tuple | None:
    """What must be unchanged for the stored answer to stand; None when that cannot be proven."""
    if files is None:
        return None
    base = Path(root)
    git_dir = _git_dir(base)
    if git_dir is None:
        return None
    try:
        head_text = (git_dir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    ref = _stat(git_dir / head_text[4:].strip()) if head_text.startswith("ref:") else None
    names = sorted({str(name).replace("\\", "/") for name in files})
    return (
        str(base),
        head_text,
        ref,
        _stat(git_dir / "packed-refs"),
        _stat(git_dir / "index"),
        _stat(git_dir / "info" / "exclude"),
        _stat(base / ".gitignore"),
        tuple((name, _stat(base / name)) for name in names),
    )


def _copy(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in evidence]


def recall(key: tuple | None) -> list[dict[str, Any]] | None:
    if key is None:
        return None
    with _lock:
        found = _entries.get(key)
        if found is None:
            return None
        _entries.move_to_end(key)
        return _copy(found)


def remember(key: tuple | None, evidence: list[dict[str, Any]]) -> None:
    if key is None:
        return
    with _lock:
        _entries[key] = _copy(evidence)
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def forget_all() -> None:
    with _lock:
        _entries.clear()


def scoped_evidence(root: str | Path, scoped: list[str] | None) -> list[dict[str, Any]]:
    """The diffs of the files a run changed that git still reports as changed; ``scoped`` None means every changed file.

    Asked twice with nothing changed in between, the second answer comes from memory. ``git status`` may rewrite its own
    index file, so the key is taken again just after it and must hold unchanged until the last diff is read: a change
    that landed while git was reading is never kept, and the second look is already fast.
    """
    stored = recall(evidence_key(root, scoped))
    if stored is not None:
        return stored
    dirty = forge_code_git.changed_files(root)
    settled = evidence_key(root, scoped)
    files = [name for name in dirty if name in scoped] if scoped is not None else dirty
    evidence = forge_code_git.change_evidence(root, files)
    if settled is not None and evidence_key(root, scoped) == settled:
        remember(settled, evidence)
    return evidence
