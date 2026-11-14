"""The file a held hand-in lives in, and the two locks around it (see :mod:`thomas.server.hand_in_hold`).

One JSON list, ``hand_in_holds.json``, in the catalog's ``.thomas/evolve/agent`` folder beside Autopilot's
usage-limit park list. Every read and write takes ``autopilot_park._parks_lock`` (this process's lock, then a lock
on a file another server's process also takes), and every write is a temporary file then ``os.replace``, so a
reader never sees half a list. :func:`change` is a compare-and-set on the row's ``gen``: a write made for an older
turn never lands on a newer turn's row.

:func:`check_claim` is a second lock, one per conversation, held for the whole length of one check. A server that
dies releases it with its process, so a restart can tell a living owner's check from an abandoned one.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from thomas.server import autopilot_park

log = logging.getLogger(__name__)
NAME = "hand_in_holds.json"


def path(catalog_root: Path) -> Path:
    return Path(catalog_root) / ".thomas" / "evolve" / "agent" / NAME


def read(catalog_root: Path) -> list[dict[str, Any]]:
    """Every row; [] before the first hold. Raises on a list it cannot read rather than lose every hold in it."""
    try:
        data = json.loads(path(catalog_root).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        log.exception("could not read the held hand-ins for %s", catalog_root)
        raise
    if not isinstance(data, list):
        raise ValueError("the held hand-ins must be a JSON list")
    return [row for row in data if isinstance(row, dict) and row.get("cid")]


def write(catalog_root: Path, rows: list[dict[str, Any]]) -> None:
    """Replace the list atomically. The caller holds ``autopilot_park._parks_lock``."""
    target = path(catalog_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, prefix=f".{NAME}.", suffix=".tmp", delete=False
        ) as handle:
            name = handle.name
            json.dump(rows, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def rows(catalog_root: Path) -> list[dict[str, Any]]:
    with autopilot_park._parks_lock(catalog_root):
        return read(catalog_root)


def row(catalog_root: Path, cid: str) -> dict[str, Any] | None:
    """A copy of this conversation's row, or None."""
    return next((dict(found) for found in rows(catalog_root) if found.get("cid") == cid), None)


def change(
    catalog_root: Path,
    cid: str,
    gen: list[Any] | None,
    update: dict[str, Any] | None,
    *,
    expected: dict[str, Any] | None = None,
) -> bool:
    """Replace (or, with ``update`` None, remove) the row, only while it is still for ``gen`` -- and, with
    ``expected``, only while it is exactly that row. False when anything else got there first."""
    with autopilot_park._parks_lock(catalog_root):
        found = read(catalog_root)
        index = next((i for i, item in enumerate(found) if item.get("cid") == cid), None)
        if index is None or gen is None or found[index].get("gen") != gen:
            return False
        if expected is not None and found[index] != expected:
            return False
        if update is None:
            found.pop(index)
        else:
            found[index] = update
        write(catalog_root, found)
        return True


@contextlib.contextmanager
def check_claim(catalog_root: Path, cid: str) -> Iterator[bool]:
    """Yield True while this process holds the one check of ``cid`` across servers, False when another has it.

    The lock file is reused across boots, and the operating system releases the lock when its process ends, so a
    server that crashed mid-check never blocks the next one, and a living server's check is never taken over.
    """
    lock = path(catalog_root).parent / f"hand-in-{hashlib.sha256(cid.encode()).hexdigest()}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return
            try:
                yield True
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def claim_free(catalog_root: Path, cid: str) -> bool:
    """Whether no process holds :func:`check_claim` for ``cid`` right now."""
    with check_claim(catalog_root, cid) as acquired:
        return acquired


__all__ = ["NAME", "change", "check_claim", "claim_free", "path", "read", "row", "rows", "write"]
