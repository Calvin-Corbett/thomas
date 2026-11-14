"""Each conversation's summary, read again only when its file changes (2026-10-27).

Listing Code conversations read and parsed every conversation file, transcripts and all, on every call: 4.4 s for
439 files on 2026-09-24, and 26 to 177 s for 709 on a busy 2026-10-27, holding a server thread the whole time. A
summary is kept for each file's modification time and size, so a listing reads only the files that changed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

_kept: dict[str, tuple[int, int, dict[str, Any]]] = {}
_lock = threading.Lock()


def summary(
    path: Path, load: Callable[[], dict[str, Any] | None], summarize: Callable[[dict[str, Any]], dict[str, Any]]
) -> dict[str, Any] | None:
    """*path*'s summary: the kept one while the file is unchanged, else ``summarize(load())`` (None if unreadable)."""
    try:
        stat = path.stat()
    except OSError:
        return None
    key = str(path)
    with _lock:
        kept = _kept.get(key)
    if kept is not None and kept[0] == stat.st_mtime_ns and kept[1] == stat.st_size:
        return dict(kept[2])
    conversation = load()
    if conversation is None:
        return None
    made = summarize(conversation)
    with _lock:
        _kept[key] = (stat.st_mtime_ns, stat.st_size, dict(made))
    return made


def forget() -> None:
    """Drop every kept summary."""
    with _lock:
        _kept.clear()


__all__ = ["forget", "summary"]
