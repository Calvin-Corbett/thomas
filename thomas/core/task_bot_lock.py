"""The file-level primitives under task-bot execution records: the per-path lock and the atomic JSON file helpers it protects.

The lock is exclusive across processes through a sidecar file (msvcrt on Windows, flock elsewhere), exclusive across threads
through one in-process lock per path, and re-entrant for the thread that holds it. task_bot_runtime builds its record and
summary locks from this class, and task_checklist_runtime locks through the runtime, so every writer of one record shares one
lock identity. Lock order is always record lock, then summary lock; never the reverse. This module imports nothing from the
runtime; the runtime re-exports these names and its callers resolve them through its own globals.
"""

from __future__ import annotations

import functools
import json
import os
import secrets
import threading
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK_TABLE: dict[str, dict[str, Any]] = {}
_LOCK_TABLE_GUARD = threading.Lock()


def _lock_handle(handle) -> None:
    if os.name == "nt":
        import msvcrt  # type: ignore

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl  # type: ignore

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_handle(handle) -> None:
    if os.name == "nt":
        import msvcrt  # type: ignore

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl  # type: ignore

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class _PathLock:
    """Exclusive cross-process lock on a sidecar file (msvcrt on Windows, flock elsewhere), re-entrant for the thread that holds
    it and exclusive across threads through an in-process lock per path. Acquisition failures raise after cleanup; nothing runs
    unprotected. Lock order in this module is always record lock, then summary lock; never the reverse."""

    def __init__(self, target: Path) -> None:
        self._key = str(target.resolve())
        self._sidecar = target.with_suffix(target.suffix + ".lock")
        with _LOCK_TABLE_GUARD:
            self._entry = _LOCK_TABLE.setdefault(
                self._key, {"lock": threading.Lock(), "owner": None, "depth": 0, "handle": None}
            )

    def __enter__(self):
        me = threading.get_ident()
        if self._entry["owner"] == me:
            self._entry["depth"] += 1
            return self
        self._entry["lock"].acquire()
        handle = None
        acquired = False
        try:
            self._sidecar.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self._sidecar, "a+b")
            _lock_handle(handle)
            acquired = True
        finally:
            # cleanup is unconditional: an interruption (KeyboardInterrupt, SystemExit) or any error during acquisition
            # closes the handle and releases the thread lock, and the release cannot be skipped by a failing close;
            # the exception itself propagates on its own
            if not acquired:
                try:
                    if handle is not None:
                        with suppress(OSError):
                            handle.close()
                finally:
                    self._entry["lock"].release()
        self._entry.update(owner=me, depth=1, handle=handle)
        return self

    def __exit__(self, exc_type, exc, tb):
        self._entry["depth"] -= 1
        if self._entry["depth"] > 0:
            return False
        handle = self._entry["handle"]
        try:
            with suppress(
                OSError, ValueError
            ):  # an unlock that fails on a closing handle must not mask the caller's outcome
                _unlock_handle(handle)
        finally:
            try:
                with suppress(OSError):
                    handle.close()
            finally:
                self._entry.update(owner=None, handle=None)
                self._entry["lock"].release()
        return False


def lock_factories(execution_path, summary_path):
    """The record lock, the summary lock and the record-mutator decorator, bound to the caller's path resolvers.

    task_bot_runtime passes callables that resolve its execution_path/summary_path at call time, so its path seams stay
    monkeypatchable; the decorator locks through the _record_lock returned here."""

    def _record_lock(execution_id: str, repo_root: str | Path | None) -> _PathLock:
        return _PathLock(execution_path(execution_id, repo_root))

    def _summary_lock(repo_root: str | Path | None) -> _PathLock:
        return _PathLock(summary_path(repo_root))

    def _locked_by_execution_id(fn):
        """Run a record mutator under that record's lock; the lock is re-entrant, so a mutator that calls update_execution keeps one lock."""

        @functools.wraps(fn)
        def inner(execution_id, *args, repo_root=None, **kwargs):
            with _record_lock(execution_id, repo_root):
                return fn(execution_id, *args, repo_root=repo_root, **kwargs)

        return inner

    return _record_lock, _summary_lock, _locked_by_execution_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    last_error: Exception | None = None
    for attempt in range(6):
        tmp = path.with_suffix(f"{path.suffix}.{secrets.token_hex(4)}.tmp")
        replaced = False
        try:
            tmp.write_text(serialized, encoding="utf-8")
            tmp.replace(path)
            replaced = True
            return
        except PermissionError as exc:  # Windows: the target is briefly open elsewhere; retried below
            last_error = exc
        finally:
            if not replaced:  # a retried or propagating failure leaves no temp file behind
                with suppress(OSError):
                    tmp.unlink(missing_ok=True)
        time.sleep(0.02 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # missing, unreadable, undecodable or malformed reads as the default
        return default
