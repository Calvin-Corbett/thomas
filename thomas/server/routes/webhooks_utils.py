"""Utility helpers shared by webhook route modules."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, Dict, Iterator


@contextlib.contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """Cross-process lock using a companion lock file."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt  # type: ignore

            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl  # type: ignore

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore

                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # type: ignore

                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            f.close()
        except Exception:
            pass


def emit_webhook_event(name: str, payload: dict[str, Any]) -> None:
    """Best-effort hook into `thomas.core.events` without strict API coupling."""
    try:
        from thomas.core import events as events_mod  # type: ignore

        for fn_name in ("emit", "publish", "send", "dispatch"):
            fn = getattr(events_mod, fn_name, None)
            if callable(fn):
                try:
                    fn(name, payload)  # type: ignore[misc]
                    return
                except TypeError:
                    try:
                        fn(event=name, payload=payload)  # type: ignore[misc]
                        return
                    except Exception:
                        return
    except Exception:
        return
