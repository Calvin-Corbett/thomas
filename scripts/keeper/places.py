"""Reading a place without trusting it: a no-follow walk, a read that notices change, and the place's state.

Every folder on the way to a file is held open (no delete or rename sharing on Windows) while that file or folder is
read, and each one is judged through its own handle, so no folder can be swapped for a junction in between. Reparse
points (junctions, symlinks, cloud placeholders) are recorded and never followed. A file is read through
``nofollow.read_regular`` and stat'ed before and after: a size, time or identity change means it changed while it was
being read, and after three tries it is refused as ``changed_while_reading``.

``place_state`` is the before/after proof for a run: every entry's kind, size and write time, and a sha256 of each file
up to ``hash_limit`` (object files under ``.git/objects`` are named by their own hash, so only their size and time are
kept). Two states compare equal only when every entry is the same.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scripts.cage.referee.nofollow import REPARSE, PortableFs, UnsafeEntry, default_fs

FILE_LIMIT = 50 * 1024 * 1024  # design 3.4: files over 50 MB are not read
STATE_HASH_LIMIT = 8 * 1024 * 1024


class KeeperFs:
    """The referee's real file seam, with one difference: a file's alternate data streams do not refuse it.

    The keeper reads only the main stream, through the same handle the referee judges (reparse point, hard link,
    sparse, size). A downloaded file's ``Zone.Identifier`` stream would otherwise make the only copy of it unsaveable.
    """

    def __init__(self, inner: PortableFs | None = None) -> None:
        self.inner = inner or default_fs()
        if hasattr(self.inner, "_streams"):
            self.inner._streams = lambda path: 1  # type: ignore[attr-defined]  # main stream only, see above

    def hold_dir(self, path: Path):
        return self.inner.hold_dir(path)

    def read_regular(self, path: Path, limit: int) -> bytes:
        return self.inner.read_regular(path, limit)


def keeper_fs() -> KeeperFs:
    return KeeperFs()


def _parts(rel: str) -> list[str]:
    return [p for p in rel.split("/") if p]


@contextmanager
def held(fs, root: Path, rel_dir: str) -> Iterator[Path]:
    """Hold ``root`` and every folder down to ``root/rel_dir``; yield that folder's path. Raises ``UnsafeEntry``."""
    with ExitStack() as stack:
        here = root
        stack.enter_context(fs.hold_dir(here))
        for part in _parts(rel_dir):
            here = here / part
            stack.enter_context(fs.hold_dir(here))
        yield here


def _same(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_size, a.st_mtime_ns, a.st_ino, getattr(a, "st_file_attributes", 0)) == (
        b.st_size,
        b.st_mtime_ns,
        b.st_ino,
        getattr(b, "st_file_attributes", 0),
    )


def read_stable(fs, path: Path, limit: int = FILE_LIMIT, tries: int = 3) -> tuple[bytes, os.stat_result]:
    """The bytes of ``path`` and its stat, read only when nothing about the file moved during the read."""
    for _ in range(tries):
        try:
            before = os.lstat(path)
        except FileNotFoundError as exc:
            raise UnsafeEntry("missing") from exc
        data = fs.read_regular(path, limit)
        try:
            after = os.lstat(path)
        except FileNotFoundError as exc:
            raise UnsafeEntry("missing", "removed while reading") from exc
        if _same(before, after) and len(data) == after.st_size:
            return data, after
    raise UnsafeEntry("changed_while_reading", f"{path} changed during {tries} reads")


def read_in_place(fs, root: Path, rel: str, limit: int = FILE_LIMIT) -> tuple[bytes, os.stat_result]:
    """Read ``root/rel`` while every folder above it is held."""
    parts = _parts(rel)
    with held(fs, root, "/".join(parts[:-1])) as folder:
        return read_stable(fs, folder / parts[-1], limit)


@dataclass
class Walk:
    files: dict[str, tuple[int, int]] = field(default_factory=dict)  # rel -> (size, mtime_ns)
    dirs: dict[str, int] = field(default_factory=dict)  # rel -> mtime_ns
    refused: dict[str, str] = field(default_factory=dict)  # rel -> code (reparse_point, not_a_plain_folder, ...)
    nested: list[str] = field(default_factory=list)  # folders holding their own .git (tree mode stops there)
    excluded: list[str] = field(default_factory=list)


def walk(
    fs,
    root: Path,
    *,
    keep_dirs: Callable[[list[str]], Iterable[str]] | None = None,
    skip_root: Iterable[str] = (),
    exclude_names: Iterable[str] = (),
    stop_at_nested_git: bool = False,
) -> Walk:
    """List ``root`` breadth first without following anything. ``keep_dirs`` gets each level's folders at once."""
    out, skip, exclude = Walk(), {s.lower() for s in skip_root}, {s.lower() for s in exclude_names}
    level = [""]
    while level:
        found: list[str] = []
        for rel in level:
            try:
                with held(fs, root, rel) as folder:
                    with os.scandir(folder) as listing:
                        entries = sorted(listing, key=lambda e: e.name)
                    if stop_at_nested_git and rel and any(e.name.lower() == ".git" for e in entries):
                        out.nested.append(rel)
                        continue
                    for entry in entries:
                        child = f"{rel}/{entry.name}" if rel else entry.name
                        if not rel and entry.name.lower() in skip:
                            continue
                        info = os.lstat(folder / entry.name)  # the entry's own record: a listing's copy lags
                        if getattr(info, "st_file_attributes", 0) & REPARSE or stat.S_ISLNK(info.st_mode):
                            out.refused[child] = "reparse_point"
                        elif stat.S_ISDIR(info.st_mode):
                            if entry.name.lower() in exclude:
                                out.excluded.append(child)
                            else:
                                out.dirs[child] = info.st_mtime_ns
                                found.append(child)
                        elif stat.S_ISREG(info.st_mode):
                            out.files[child] = (info.st_size, info.st_mtime_ns)
                        else:
                            out.refused[child] = "not_a_file"
            except UnsafeEntry as exc:
                out.refused[rel or "."] = exc.code
            except OSError as exc:
                out.refused[rel or "."] = f"unreadable: {exc.strerror or exc}"
        level = sorted(keep_dirs(found)) if keep_dirs is not None and found else found
    return out


def _skip_hash(rel: str) -> bool:
    low = "/" + rel.lower()
    return "/.git/objects/" in low


def place_state(root: Path, *, fs=None, hash_limit: int = STATE_HASH_LIMIT) -> dict:
    """Every entry under ``root`` with kind, size, write time and (for files up to ``hash_limit``) its sha256."""
    fs = fs or keeper_fs()
    root = Path(os.path.abspath(root))
    found = walk(fs, root)
    entries: dict[str, list] = {}
    for rel, mtime in found.dirs.items():
        entries[rel] = ["dir", 0, mtime, None]
    for rel, (size, mtime) in found.files.items():
        digest: str | None = None
        if size <= hash_limit and not _skip_hash(rel):
            try:
                data, _ = read_in_place(fs, root, rel, hash_limit)
                digest = hashlib.sha256(data).hexdigest()
            except UnsafeEntry as exc:
                digest = f"refused:{exc.code}"
        entries[rel] = ["file", size, mtime, digest]
    for rel, code in found.refused.items():
        try:  # a link's own size and time, never its target's
            info = os.lstat(root / rel) if rel != "." else os.lstat(root)
            entries[rel] = ["link" if code == "reparse_point" else "refused", info.st_size, info.st_mtime_ns, code]
        except OSError:
            entries[rel] = ["refused", 0, 0, code]
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "root": str(root),
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(entries),
        "digest": hashlib.sha256(canonical).hexdigest(),
        "entries": entries,
    }


def compare_states(before: dict, after: dict) -> list[str]:
    """Human lines naming every entry that differs; empty when the two states are the same."""
    a, b = before["entries"], after["entries"]
    lines = [f"removed: {p}" for p in sorted(set(a) - set(b))]
    lines += [f"added: {p}" for p in sorted(set(b) - set(a))]
    lines += [f"changed: {p} {a[p]} -> {b[p]}" for p in sorted(set(a) & set(b)) if a[p] != b[p]]
    return lines
