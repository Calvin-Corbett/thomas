#!/usr/bin/env python3
"""Workboard file locking and atomic write helpers."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_LOCK_DEPTHS: dict[tuple[str, int], int] = {}


def _remove_lock_file(lock_file: Path, *, attempts: int = 20, delay: float = 0.05) -> bool:
    for attempt in range(attempts):
        try:
            lock_file.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt == attempts - 1:
                return False
            time.sleep(delay)
    return False


@contextmanager
def _file_lock(lock_file: Path, timeout: float = 10.0, stale_seconds: float = 60.0) -> Iterator[None]:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_key = str(lock_file.resolve())
    thread_id = threading.get_ident()
    depth_key = (lock_key, thread_id)
    depth = _LOCK_DEPTHS.get(depth_key, 0)
    if depth > 0:
        _LOCK_DEPTHS[depth_key] = depth + 1
        try:
            yield
        finally:
            remaining = _LOCK_DEPTHS.get(depth_key, 1) - 1
            if remaining > 0:
                _LOCK_DEPTHS[depth_key] = remaining
            else:
                _LOCK_DEPTHS.pop(depth_key, None)
        return

    fd: int | None = None
    deadline = time.time() + timeout
    owner_marker = f"pid={os.getpid()}; thread={thread_id};"
    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(
                fd,
                (
                    f"{owner_marker} acquired_at={datetime.now(timezone.utc).replace(microsecond=0).isoformat()}\n"
                ).encode(),
            )
            _LOCK_DEPTHS[depth_key] = 1
            break
        except FileExistsError:
            try:
                owner_text = lock_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                owner_text = ""
            if owner_marker in owner_text:
                yield
                return
            try:
                age = time.time() - lock_file.stat().st_mtime
            except FileNotFoundError:
                age = 0.0
            if age > stale_seconds and _remove_lock_file(lock_file):
                continue
            if time.time() >= deadline:
                raise TimeoutError(f"timed out waiting for lock: {lock_file}")
            time.sleep(0.05)

    try:
        yield
    finally:
        remaining = _LOCK_DEPTHS.get(depth_key, 1) - 1
        if remaining > 0:
            _LOCK_DEPTHS[depth_key] = remaining
        else:
            _LOCK_DEPTHS.pop(depth_key, None)
            if fd is not None:
                os.close(fd)
            _remove_lock_file(lock_file)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        for attempt in range(20):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
