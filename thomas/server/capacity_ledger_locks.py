"""The locks under the machine-wide reservation ledger (:mod:`thomas.server.capacity_ledger`), and whose rows live.

Every read and write of a ledger file holds this process's lock, then a lock on a file beside it that the other
server's process also takes (``autopilot_park._parks_lock``'s pattern). Each process also holds its own
``owner-<pid>-<token>.lock`` in the ledger's folder for its whole life: a row whose owner lock can be taken belongs to
a process that has died. A row of this process lives only while one of its jobs holds it (:func:`hold`), so a row
whose release could not be written is dropped by this process's next look at the ledger (:func:`alive`).

A ledger file that cannot be read is never taken for an empty one (:func:`read_rows`): the next write would erase
every other server's reservations. A server counts as possibly holding rows in it only if it started before the file
was last written: a process started later cannot have written into it, so servers that all started after a power cut
left the file empty recover it themselves.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

from thomas.server import capacity_ledger_file as ledger_file

log = logging.getLogger(__name__)

WAIT_LIMIT_S = 60.0  # a peer that froze while holding the file lock must not hang every ledger call for good
_RETRY_S = 0.015
READ_TRIES = 5  # a file another handle holds without sharing is read again this often (machine_capacity's pattern)
READ_WAIT_S = 0.02
_lock = threading.Lock()
_owners: dict[str, tuple[str, IO[bytes]]] = {}
_owners_lock = threading.Lock()
_held: set[str] = set()  # the keys of this process's rows that one of its jobs still holds
_held_lock = threading.Lock()


class LedgerUnreadable(OSError):
    """The ledger file is not a list of whole rows, and a job of this process or an older server may have rows in it."""


def _try_lock(handle: IO[bytes]) -> bool:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def lock_file(handle: IO[bytes], *, wait: bool) -> bool:
    """Lock the first byte of *handle* against every process; False when *wait* is off and another holds it.

    With *wait* it tries again every 15 ms (``msvcrt.LK_LOCK`` would wait a whole second between tries and give up
    after ten) and raises :class:`TimeoutError`, an ``OSError``, after :data:`WAIT_LIMIT_S` seconds.
    """
    ends = time.monotonic() + WAIT_LIMIT_S
    while not _try_lock(handle):
        if not wait:
            return False
        if time.monotonic() >= ends:
            raise TimeoutError(f"{getattr(handle, 'name', 'a lock file')} stayed locked for {WAIT_LIMIT_S:g} s")
        time.sleep(_RETRY_S)
    return True


def unlock_file(handle: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def locked(place: Path, name: str) -> Iterator[None]:
    """This process's lock, then the file lock on ``<name>.lock`` in *place* that every server's process takes."""
    place.mkdir(parents=True, exist_ok=True)
    with _lock, open(place / f"{name}.lock", "a+b") as handle:
        lock_file(handle, wait=True)
        try:
            yield
        finally:
            unlock_file(handle)


def owner(place: Path) -> str:
    """This process's owner name in *place*; its lock file stays locked until the process ends."""
    with _owners_lock:
        held = _owners.get(str(place))
        if held is None:
            place.mkdir(parents=True, exist_ok=True)
            name = f"owner-{os.getpid()}-{uuid.uuid4().hex[:8]}"
            handle = open(place / f"{name}.lock", "a+b")  # noqa: SIM115 -- kept open for the process's life
            if not lock_file(handle, wait=False):  # rows under an owner every peer judges dead would be dropped
                handle.close()
                (place / f"{name}.lock").unlink(missing_ok=True)
                raise OSError(f"could not lock this process's own owner file {name}.lock in {place}")
            held = _owners[str(place)] = (name, handle)
        return held[0]


def owner_alive(place: Path, name: str) -> bool:
    """Whether the process that owns *name* in *place* still runs; a dead owner's lock file is removed."""
    path = place / f"{name}.lock"
    if not name.startswith("owner-") or not path.is_file():
        return False
    try:
        handle = open(path, "a+b")  # noqa: SIM115 -- closed below
    except OSError:
        return True  # it cannot even be opened: never drop a row that may be live
    try:
        if not lock_file(handle, wait=False):
            return True
        unlock_file(handle)
    finally:
        handle.close()
    with contextlib.suppress(OSError):
        path.unlink()
    return False


def _raw(path: Path) -> bytes | None:
    for attempt in range(READ_TRIES):
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except PermissionError:  # a third party holds the file without sharing it this instant (Windows)
            if attempt == READ_TRIES - 1:
                raise
            time.sleep(READ_WAIT_S * (attempt + 1))
    return None


def _last_written(path: Path) -> float:
    """When *path* was last written; a time that cannot be told is the far future, which counts against moving it."""
    try:
        return path.stat().st_mtime
    except OSError:
        return math.inf


def _started_before(lock_file_path: Path, moment: float) -> bool:
    """Whether the process that made the owner lock file *lock_file_path* began using the ledger by *moment*.

    The file is made at the process's first look at the ledger, before it can write a row, and is never written, so its
    creation time (where the system keeps one) and its modification time both say when. The earlier counts, and a time
    that cannot be told counts as before.
    """
    try:
        info = lock_file_path.stat()
    except OSError:
        return True
    return min(info.st_mtime, getattr(info, "st_birthtime", info.st_mtime)) <= moment


def read_rows(place: Path, name: str) -> list[dict[str, Any]]:
    """The rows of the JSON list *name* in *place*, read under :func:`locked`. It never returns [] for a failed read.

    A missing file is an empty ledger. A busy file (``PermissionError``) is read again a few times and then the error
    is raised, so the caller never writes a ledger it could not read. A file that is not a JSON list (bad text, or so
    deeply nested that it overflows the parser), or holds a row with a field missing or of the wrong type
    (:func:`~thomas.server.capacity_ledger_file.problem`), raises :class:`LedgerUnreadable` while a job of this process
    holds a row or a live server of another process started before the file was last written, and is left as it is,
    since their rows may be in it. With neither it is moved aside to ``<name>.corrupt-<seconds>-<token>``, logged, and
    the ledger starts empty.
    """
    path = place / name
    raw = _raw(path)
    if raw is None:
        return []
    try:
        found = json.loads(raw.decode("utf-8"))
        if not isinstance(found, list):
            raise ValueError("it is not a list")
        for row in found:
            if wrong := ledger_file.problem(row):
                raise ValueError(wrong)
    except (ValueError, RecursionError) as exc:
        me, written = owner(place), _last_written(path)
        with _held_lock:
            running = bool(_held)
        if running or any(
            peer.stem != me and owner_alive(place, peer.stem) and _started_before(peer, written)
            for peer in sorted(place.glob("owner-*.lock"))
        ):
            raise LedgerUnreadable(f"{path} cannot be read ({exc}) and rows of a running job may be in it") from exc
        aside = path.with_name(f"{name}.corrupt-{int(time.time())}-{uuid.uuid4().hex[:6]}")
        os.replace(path, aside)
        log.error("%s could not be read (%s): moved to %s, and the ledger starts empty", path, exc, aside.name)
        return []
    return found


def hold(key: str) -> None:
    """One of this process's jobs holds the row *key*: it lives until :func:`let_go`."""
    with _held_lock:
        _held.add(key)


def let_go(key: str) -> None:
    with _held_lock:
        _held.discard(key)


def alive(place: Path, found: list[dict[str, Any]], *, standing: str) -> tuple[list[dict[str, Any]], bool]:
    """The rows of *found* still live, and whether any were dropped.

    Another process's row lives while that process does. This process's own row lives while one of its jobs holds it
    (:func:`hold`), or when its kind is *standing*, which this process keeps for its life: so a row its release could
    not remove is dropped here.
    """
    me = owner(place)
    with _held_lock:
        held = set(_held)
    verdicts: dict[str, bool] = {}
    kept = []
    for row in found:
        name = str(row.get("owner") or "")
        if name == me:
            live = row.get("kind") == standing or row.get("key") in held
        else:
            if name not in verdicts:
                verdicts[name] = owner_alive(place, name)
            live = verdicts[name]
        if live:
            kept.append(row)
    return kept, len(kept) != len(found)


__all__ = [
    "READ_TRIES",
    "READ_WAIT_S",
    "WAIT_LIMIT_S",
    "LedgerUnreadable",
    "alive",
    "hold",
    "let_go",
    "lock_file",
    "locked",
    "owner",
    "owner_alive",
    "read_rows",
    "unlock_file",
]
