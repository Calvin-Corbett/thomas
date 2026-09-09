"""A content manifest for a project folder that has no version history (2026-09-05).

A person may open a plain folder in Build and choose to work without history.
The run still has to say what it changed, truthfully: this manifest is the
snapshot taken before the run (path, size, sha256 of every file the person
owns) and the delta is what differs afterwards. It is not git and never
pretends to be: there is no diff text and no undo, and every row says so.

It fails closed, whole. Every entry is a real streamed sha256 of the file's
content; there is no sentinel a finalizer could read as "unchanged". A file
that cannot be read, a directory that cannot be listed, more files than the
bound, or more bytes than the bound refuse the snapshot with a clear error
rather than attribute part of the folder. The scan is confined: a link or
junction whose target lies outside the folder is not followed, and Thomas's
own bookkeeping and the usual dependency folders are skipped.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

MARKER = "\0manifest"  # a key no relative path can be: filenames cannot contain NUL on any OS
MAX_FILES = 20000
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024  # the honest bound on hashing work, refused past it
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".thomas",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        "thomas_rag_index",
    }
)


class ManifestError(RuntimeError):
    """The folder cannot be attributed whole; nothing partial is returned."""


class ManifestTooLarge(ManifestError):
    """More files or bytes than the manifest may attribute."""


class ManifestUnreadable(ManifestError):
    """A file or directory could not be read; attribution would have a hole."""


def is_manifest(snap: dict[str, str] | None) -> bool:
    return bool(snap) and snap.get(MARKER) == "1"


def _fingerprint(path: Path, st: os.stat_result) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}:{st.st_size}"


def _inside(base: Path, candidate: Path) -> bool:
    """True when ``candidate`` resolves (through links and junctions) to inside ``base``."""
    try:
        return candidate.resolve().is_relative_to(base)
    except OSError:
        return False


def _real_directory(here: Path, name: str, seen: set[Path]) -> bool:
    """True for a plain directory not walked before. A symlink or junction resolves
    to a path other than its own and is never entered, wherever it points: one
    back into the folder would otherwise walk forever (``os.walk`` does not treat
    a Windows junction as a link)."""
    full = here / name
    try:
        resolved = full.resolve()
    except OSError:
        return False
    if resolved != full or resolved in seen:
        return False
    seen.add(resolved)
    return True


def snapshot(root: str | Path, *, max_files: int | None = None, max_total_bytes: int | None = None) -> dict[str, str]:
    """``{relative posix path: sha256:<hex>:<size>}`` for every file under ``root``, plus the marker.

    Raises :class:`ManifestTooLarge` past the bounds and :class:`ManifestUnreadable`
    for anything the scan could not read, instead of returning part of the folder.
    """

    base = Path(root).resolve()
    file_limit = int(max_files) if max_files is not None else MAX_FILES  # read at call time
    byte_limit = int(max_total_bytes) if max_total_bytes is not None else MAX_TOTAL_BYTES
    out: dict[str, str] = {MARKER: "1"}
    count = 0
    total = 0

    def refuse_listing(err: OSError) -> None:
        raise ManifestUnreadable(f"cannot list {err.filename or base}: {err.strerror or err}") from err

    seen: set[Path] = {base}
    for dirpath, dirnames, filenames in os.walk(base, onerror=refuse_listing):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and _real_directory(here, d, seen))
        for name in sorted(filenames):
            full = here / name
            if not _inside(base, full):
                continue
            rel = full.relative_to(base).as_posix()
            try:
                st = full.stat()
                if not os.path.isfile(full):
                    continue
                count += 1
                total += st.st_size
                if count > file_limit:
                    raise ManifestTooLarge(f"{base.name} has more than {file_limit} files; too many to attribute")
                if total > byte_limit:
                    raise ManifestTooLarge(f"{base.name} holds more than {byte_limit} bytes; too much to attribute")
                out[rel] = _fingerprint(full, st)
            except OSError as exc:
                raise ManifestUnreadable(f"cannot read {rel}: {exc.strerror or exc}") from exc
    return out


def _entries(snap: dict[str, str] | None) -> dict[str, str]:
    return {k: v for k, v in (snap or {}).items() if k != MARKER}


def delta_since(root: str | Path, snap: dict[str, str]) -> list[str]:
    """Paths added, modified or deleted since ``snap``, sorted."""

    before = _entries(snap)
    now = _entries(snapshot(root))
    changed = {p for p, fp in now.items() if before.get(p) != fp}
    changed |= {p for p in before if p not in now}
    return sorted(changed)


def change_evidence(root: str | Path, files: list[str], snap: dict[str, str]) -> list[dict[str, Any]]:
    """Per-file attribution with hashes; no diff text and no undo, and each row says so."""

    before = _entries(snap)
    now = _entries(snapshot(root))
    rows: list[dict[str, Any]] = []
    for file in files:
        was, is_now = str(before.get(file) or ""), str(now.get(file) or "")
        if was and not is_now:
            status = "deleted"
        elif is_now and not was:
            status = "added"
        elif was != is_now:
            status = "modified"
        else:
            status = "unchanged"
        rows.append(
            {
                "file": file,
                "status": status,
                "before": was,
                "after": is_now,
                "untracked": not was,
                "diff": "",
                "history_available": False,
                "note": "this folder has no version history: the change is attributed by content hash; no diff, no undo",
            }
        )
    return rows


__all__ = [
    "MARKER",
    "ManifestError",
    "ManifestTooLarge",
    "ManifestUnreadable",
    "change_evidence",
    "delta_since",
    "is_manifest",
    "snapshot",
]
