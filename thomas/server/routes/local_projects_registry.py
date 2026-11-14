"""Per-app serialization and atomic persistence for the local project registry."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import weakref
from collections.abc import Awaitable, Callable
from functools import wraps
from pathlib import Path
from typing import Any

from aiohttp import web

REGISTRY_LOCK_KEY = "_thomas_projects_registry_lock"
CATALOGUE_CACHE_KEY = "_thomas_projects_cache"

# For an app whose local project routes are turned off. Chat and the workspace specialist still read and change the
# registry then, and a key cannot be added to a running app.
_LOCKS: weakref.WeakKeyDictionary[web.Application, asyncio.Lock] = weakref.WeakKeyDictionary()


def registry_lock(app: web.Application) -> asyncio.Lock:
    """Return the lock installed when local project routes are registered, or this app's own while they are off."""
    lock = app.get(REGISTRY_LOCK_KEY)
    if lock is None and isinstance(app, web.Application):
        lock = _LOCKS.setdefault(app, asyncio.Lock())
    return lock if lock is not None else app[REGISTRY_LOCK_KEY]


async def stop_catalogue_rebuild(app: Any) -> None:
    """End a catalogue rebuild that is still going, so a stopped server is not left holding one.

    The scan itself runs in a worker thread that Python cannot end, so it finishes by itself and its result is dropped.
    """
    slot = app.get(CATALOGUE_CACHE_KEY)
    task = slot.get("task") if isinstance(slot, dict) else None
    if task is None or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def registry_mutation(handler: Callable[..., Awaitable[web.Response]]) -> Callable[..., Awaitable[web.Response]]:
    """Serialize a route's read/modify/write cycle without blocking the loop."""

    @wraps(handler)
    async def locked(request: web.Request) -> web.Response:
        async with registry_lock(request.app):
            return await handler(request)

    return locked


def write_registry_atomically(path: Path, data: dict[str, Any]) -> None:
    """Replace a complete registry; readers never observe a truncated JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = stream.name
            json.dump(data, stream)
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
