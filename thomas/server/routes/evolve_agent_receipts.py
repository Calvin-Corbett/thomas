"""Serialized, fail-closed persistence for directed Code action receipts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from thomas.core.config import resolve_thomas_data_dir

from .webhooks_utils import file_lock

_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()
# Cache only the small layout marker, never the growing receipt history.
_KNOWN: dict[str, tuple[tuple[int, int], dict[str, dict[str, Any]]]] = {}
_KNOWN_GUARD = threading.Lock()
_LAYOUT = {"receipt_store": {"version": 2, "directory": "action_receipts"}}


def _receipt_path(root: Path) -> Path:
    repo_key = hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode("utf-8")).hexdigest()
    directory = resolve_thomas_data_dir() / "forge_code" / repo_key
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "action_receipts.json"


def _receipt_key(kind: str, request_id: str) -> str:
    return hashlib.sha256(f"{kind}:{request_id}".encode()).hexdigest()


def _process_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())


def _stamp(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size) of *path*; None when it does not exist or cannot be looked at (then it is read in full)."""
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size


def _copy(receipts: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Callers update a receipt in place before saving it; that must never reach the kept copy."""
    return copy.deepcopy(receipts)


def _keep(path: Path, receipts: dict[str, dict[str, Any]]) -> None:
    stamp = _stamp(path)
    with _KNOWN_GUARD:
        if stamp is not None and receipts == _LAYOUT:
            _KNOWN[os.path.normcase(str(path))] = (stamp, _copy(receipts))
        else:
            _KNOWN.pop(os.path.normcase(str(path)), None)


def _read_receipts_path(path: Path, *, missing_ok: bool = False) -> dict[str, dict[str, Any]]:
    stamp = _stamp(path)  # taken before the read: a write in between only makes the next look read again
    with _KNOWN_GUARD:
        known = _KNOWN.get(os.path.normcase(str(path)))
    if stamp is not None and known is not None and known[0] == stamp:
        return _copy(known[1])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        if missing_ok:
            return {}
        raise RuntimeError("Code action receipts are missing; refusing an unsafe replay") from exc
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise RuntimeError("Code action receipts are unreadable; refusing an unsafe replay") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Code action receipts have an invalid format")
    if any(not isinstance(value, dict) for value in data.values()):
        raise RuntimeError("Code action receipts contain an invalid entry; refusing an unsafe replay")
    if stamp is not None and data == _LAYOUT:
        with _KNOWN_GUARD:
            _KNOWN[os.path.normcase(str(path))] = (stamp, _copy(data))
    return data


def _entry_path(path: Path, key: str) -> Path:
    if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
        raise RuntimeError("Code action receipts contain an invalid key; refusing an unsafe replay")
    return path.with_suffix("") / key[:2] / f"{key}.json"


def _index_path(directory: Path) -> Path:
    return directory / "request_ids.sqlite3"


@contextmanager
def _index(path: Path, *, create: bool = False):
    index_path = _index_path(path)
    if not create and not index_path.is_file():
        raise RuntimeError("Code action receipt index is missing; refusing an unsafe replay")
    connection = None
    try:
        connection = (
            sqlite3.connect(index_path)
            if create
            else sqlite3.connect(index_path.resolve().as_uri() + "?mode=rw", uri=True)
        )
        connection.execute("PRAGMA synchronous=FULL")
        if create:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, deleted INTEGER NOT NULL) WITHOUT ROWID"
            )
            connection.commit()
        columns = connection.execute("PRAGMA table_info(requests)").fetchall()
        if columns != [(0, "key", "TEXT", 1, None, 1), (1, "deleted", "INTEGER", 1, None, 0)]:
            raise RuntimeError("Code action receipt index has an invalid schema; refusing an unsafe replay")
        yield connection
        connection.commit()
    except sqlite3.Error as exc:
        raise RuntimeError("Code action receipt index is unreadable; refusing an unsafe replay") from exc
    finally:
        if connection is not None:
            connection.close()


def _store(path: Path) -> Path:
    """Migrate under the original lock; publish the marker after receipts and IDs."""
    directory = path.with_suffix("")
    data = _read_receipts_path(path, missing_ok=not directory.exists())
    if data == _LAYOUT:
        if not directory.is_dir():
            raise RuntimeError("Code action receipt directory is missing; refusing an unsafe replay")
        return directory
    # Validate the entire legacy mapping before writing any files.
    entries = [(_entry_path(path, key), value) for key, value in data.items()]
    # Establish a retryable legacy source before creating any new-store artifacts.
    if not path.exists():
        _write_receipts(path, data)
    directory.mkdir(parents=True, exist_ok=True)
    for entry, value in entries:
        entry.parent.mkdir(parents=True, exist_ok=True)
        _write_receipts(entry, {entry.stem: value})
    with _index(directory, create=True) as index:
        index.executemany("INSERT OR REPLACE INTO requests VALUES (?, 0)", ((entry.stem,) for entry, _ in entries))
        index.commit()
    _write_receipts(path, _LAYOUT)
    return directory


def _read_entry(path: Path, key: str) -> dict[str, Any] | None:
    data = _read_receipts_path(path, missing_ok=True)
    if not data and not path.exists():
        return None
    if set(data) != {key}:
        raise RuntimeError("Code action receipt has an invalid key; refusing an unsafe replay")
    return data[key]


def _read_receipts(root: Path) -> dict[str, dict[str, Any]]:
    path = _receipt_path(root)
    with _process_lock(path), file_lock(path.with_suffix(".lock")):
        directory = _store(path)
        with _index(directory) as index:
            rows = index.execute("SELECT key, deleted FROM requests WHERE deleted != 1").fetchall()
            history = {}
            for key, state in rows:
                if state == 2 and not _entry_path(path, key).exists():
                    history[key] = {"state": "persistence_failed"}
                else:
                    history[key] = _indexed_entry(path, key, index)
            return history


def _action_receipt(root: Path, kind: str, request_id: str) -> dict[str, Any] | None:
    path = _receipt_path(root)
    with _process_lock(path), file_lock(path.with_suffix(".lock")):
        _store(path)
        key = _receipt_key(kind, request_id)
        return _indexed_entry(path, key)


def _indexed_entry(path: Path, key: str, index: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    if index is None:
        with _index(path.with_suffix("")) as connection:
            return _indexed_entry(path, key, connection)
    row = index.execute("SELECT deleted FROM requests WHERE key = ?", (key,)).fetchone()
    if row is not None and (type(row[0]) is not int or row[0] not in (0, 1, 2)):
        raise RuntimeError("Code action receipt index has an invalid state; refusing an unsafe replay")
    entry = _entry_path(path, key)
    if row == (1,):
        return None  # Explicit rollback before launch permits retry, unlike lost receipt data.
    receipt = _read_entry(entry, key)
    if row is not None and receipt is None:
        raise RuntimeError("Code action receipt is missing; refusing an unsafe replay")
    if row is None and receipt is not None:
        raise RuntimeError("Code action receipt index is incomplete; refusing an unsafe replay")
    return receipt


def _write_receipts(path: Path, receipts: dict[str, dict[str, Any]]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            # Compact and in one write: an indent makes json use its pure-Python encoder, about five times slower,
            # and json.dump writes chunk by chunk.
            handle.write(json.dumps(receipts, ensure_ascii=False, separators=(",", ":")))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _keep(path, receipts)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _save_action_receipt(root: Path, kind: str, request_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    path = _receipt_path(root)
    with _process_lock(path), file_lock(path.with_suffix(".lock")):
        directory = _store(path)
        key = _receipt_key(kind, request_id)
        entry = _entry_path(path, key)
        entry.parent.mkdir(parents=True, exist_ok=True)
        previous = _indexed_entry(path, key)
        if previous is None:
            entry.unlink(missing_ok=True)
            with _index(directory) as index:
                index.execute("INSERT OR REPLACE INTO requests VALUES (?, 2)", (key,))
        _write_receipts(entry, {key: receipt})
        with _index(directory) as index:
            index.execute("UPDATE requests SET deleted = 0 WHERE key = ?", (key,))
    return receipt


def _delete_action_receipt(root: Path, kind: str, request_id: str) -> None:
    path = _receipt_path(root)
    with _process_lock(path), file_lock(path.with_suffix(".lock")):
        directory = _store(path)
        key = _receipt_key(kind, request_id)
        if _indexed_entry(path, key) is not None:
            with _index(directory) as index:
                index.execute("UPDATE requests SET deleted = 1 WHERE key = ?", (key,))
        _entry_path(path, key).unlink(missing_ok=True)
