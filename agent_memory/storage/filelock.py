from __future__ import annotations
import os
import time
from contextlib import contextmanager

try:
    import msvcrt  # type: ignore
    _HAS_MSVCRT = True
except Exception:
    _HAS_MSVCRT = False

try:
    import fcntl  # type: ignore
    _HAS_FCNTL = True
except Exception:
    _HAS_FCNTL = False

@contextmanager
def file_lock(lock_path: str, timeout_s: float = 10.0, poll_s: float = 0.05):
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    f = open(lock_path, "a+b")
    start = time.time()
    acquired = False
    try:
        while True:
            try:
                if _HAS_MSVCRT:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                elif _HAS_FCNTL:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                else:
                    acquired = True
                    break
            except Exception:
                if time.time() - start > timeout_s:
                    raise TimeoutError(f"Could not acquire lock: {lock_path}")
                time.sleep(poll_s)
        yield
    finally:
        try:
            if acquired:
                if _HAS_MSVCRT:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                elif _HAS_FCNTL:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            try:
                f.close()
            except Exception:
                pass
