#!/usr/bin/env python3
"""Shared locking and atomic publication for WORKBOARD updates."""

from __future__ import annotations

import errno
import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

_LOCAL_ROOT = Path(__file__).resolve().parents[3]


def _canonical_repo_root() -> Path:
    """Return the primary checkout so linked worktrees share one lock."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(_LOCAL_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            common = Path(result.stdout.strip())
            if common.name == ".git" and common.parent.exists():
                return common.parent
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return _LOCAL_ROOT


ROOT = _canonical_repo_root()
COORDINATION_DIR = ROOT / "runtime" / "coordination"
LOCK_FILE = COORDINATION_DIR / "workboard.lock"
LOCK_TIMEOUT_SECONDS = 10.0
LOCK_STALE_SECONDS = 60.0
ATOMIC_REPLACE_ATTEMPTS = 8
ATOMIC_REPLACE_INITIAL_BACKOFF_SECONDS = 0.025
ATOMIC_REPLACE_MAX_BACKOFF_SECONDS = 0.2

_THREAD_STATE = threading.local()
_P = ParamSpec("_P")
_R = TypeVar("_R")


def _lock_depths() -> dict[str, int]:
    depths = getattr(_THREAD_STATE, "lock_depths", None)
    if depths is None:
        depths = {}
        _THREAD_STATE.lock_depths = depths
    return depths


def _lock_key(lock_file: Path) -> str:
    return os.path.normcase(str(lock_file.absolute()))


def _read_lock_owner(lock_file: Path) -> tuple[int, str] | None:
    try:
        payload = json.loads(lock_file.read_text(encoding="utf-8"))
        pid = int(payload.get("pid", 0))
        token = str(payload.get("token", "")).strip()
    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if pid <= 0 or not token:
        return None
    return pid, token


def _process_is_alive(pid: int) -> bool | None:
    """Return None when liveness cannot be proven either way."""
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            query_limited_information = 0x1000
            still_active = 259
            invalid_parameter = 87
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            handle = kernel32.OpenProcess(query_limited_information, False, pid)
            if not handle:
                if ctypes.get_last_error() == invalid_parameter:
                    return False
                return None
            exit_code = ctypes.c_ulong()
            try:
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return None
                return int(exit_code.value) == still_active
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return None
    return True


def _unlink_if_owned(lock_file: Path, token: str) -> bool:
    owner = _read_lock_owner(lock_file)
    if owner is None or owner[1] != token:
        return False
    try:
        lock_file.unlink()
    except FileNotFoundError:
        return False
    return True


def _break_abandoned_lock(lock_file: Path) -> bool:
    """Remove an old lock only after proving its recorded process is dead."""
    try:
        age = time.time() - lock_file.stat().st_mtime
    except (FileNotFoundError, PermissionError):
        return False
    if age <= LOCK_STALE_SECONDS:
        return False
    owner = _read_lock_owner(lock_file)
    if owner is None or _process_is_alive(owner[0]) is not False:
        return False

    breaker = lock_file.with_name(f".{lock_file.name}.breaker")
    breaker_fd: int | None = None
    try:
        breaker_fd = os.open(str(breaker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except (FileExistsError, PermissionError):
        return False
    try:
        current = _read_lock_owner(lock_file)
        if current != owner or _process_is_alive(owner[0]) is not False:
            return False
        return _unlink_if_owned(lock_file, owner[1])
    finally:
        if breaker_fd is not None:
            os.close(breaker_fd)
        try:
            breaker.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def file_lock(
    lock_file: Path = LOCK_FILE,
    timeout: float = LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire the cross-process board lock, reentrantly in one thread."""
    key = _lock_key(lock_file)
    depths = _lock_depths()
    if depths.get(key, 0):
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd: int | None = None
    token = uuid.uuid4().hex
    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            if _break_abandoned_lock(lock_file):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock: {lock_file}") from None
            time.sleep(0.05)
            continue
        try:
            payload = {"pid": os.getpid(), "token": token, "created_at": time.time()}
            os.write(fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
        except OSError:
            os.close(fd)
            fd = None
            try:
                lock_file.unlink()
            except FileNotFoundError:
                pass
            raise
        break

    depths[key] = 1
    try:
        yield
    finally:
        depths.pop(key, None)
        if fd is not None:
            os.close(fd)
        _unlink_if_owned(lock_file, token)


def transaction(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Wrap a complete WORKBOARD read-modify-write operation."""

    @wraps(func)
    def _locked(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with file_lock():
            return func(*args, **kwargs)

    return _locked


def _is_retryable_replace_error(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) in {5, 32} or exc.errno == errno.EACCES


def _replace_with_retry(tmp: Path, destination: Path) -> None:
    delay = ATOMIC_REPLACE_INITIAL_BACKOFF_SECONDS
    for attempt in range(ATOMIC_REPLACE_ATTEMPTS):
        try:
            tmp.replace(destination)
            return
        except OSError as exc:
            if not _is_retryable_replace_error(exc) or attempt + 1 >= ATOMIC_REPLACE_ATTEMPTS:
                raise
            time.sleep(delay)
            delay = min(delay * 2, ATOMIC_REPLACE_MAX_BACKOFF_SECONDS)


def atomic_write(
    path: Path,
    text: str,
    *,
    validator: Callable[[Path], Sequence[str]] | None = None,
) -> list[str]:
    """Validate a temporary candidate and atomically publish it under the lock."""
    with file_lock():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            violations = list(validator(tmp)) if validator is not None else []
            if violations:
                return violations
            _replace_with_retry(tmp, path)
            return []
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def validated_update(
    path: Path,
    original_text: str,
    new_text: str,
    *,
    validator: Callable[[Path], Sequence[str]],
) -> list[str]:
    """Publish a valid candidate only if its read snapshot is still current."""
    with file_lock():
        current_text = path.read_text(encoding="utf-8")
        if current_text != original_text:
            return ["workboard changed during update; retry the operation"]
        return atomic_write(path, new_text, validator=validator)
