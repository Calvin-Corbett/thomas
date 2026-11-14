"""Parsed conversation records retained only while the restart survey retries."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def read_conversation(path: Path, cache: dict[Path, tuple[int, int, Any]]) -> Any:
    from thomas.server.routes.self_project_listing_cache import read_conversation as parse

    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = cache.get(path)
        if cached is not None and cached[:2] == stamp:
            return cached[2]
        conversation = parse(path)
        after = path.stat()
        if (after.st_mtime_ns, after.st_size) == stamp:
            cache[path] = (*stamp, conversation)
        else:
            cache.pop(path, None)
        return conversation
    except (OSError, ValueError, MemoryError, RecursionError):
        cache.pop(path, None)
        raise
