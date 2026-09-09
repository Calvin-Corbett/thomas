from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from collections.abc import AsyncIterator
from typing import Any


def utc_ms() -> int:
    return int(time.time() * 1000)


def sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


@contextlib.asynccontextmanager
async def cancel_on_exit(task: asyncio.Task | None):
    try:
        yield
    finally:
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(Exception):
                await task


class AsyncCancelScope:
    """A small utility to manage cancellable background tasks."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def create(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(lambda _t: self._tasks.discard(_t))
        return t

    async def cancel_all(self):
        for t in list(self._tasks):
            if not t.done():
                t.cancel()
        for t in list(self._tasks):
            with contextlib.suppress(Exception):
                await t
        self._tasks.clear()


async def aiter_from_list(items: list[Any]) -> AsyncIterator[Any]:
    for x in items:
        yield x
