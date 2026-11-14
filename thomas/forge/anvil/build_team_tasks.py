"""Own, cancel and join a bounded Build team on all supported Python versions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from .run_control import held_deadline


async def run_owned_builders(
    jobs: Sequence[dict[str, str]],
    build: Callable[[int, dict[str, str]], Awaitable[Any]],
    *,
    deadline: float,
    team_id: str,
) -> None:
    """Return only after every owned child settles, including repeated Stop.

    In a Build pass with controls the wait is held time while you have the run paused: ``deadline`` becomes a
    :class:`~.run_control.HeldDeadline` on the pass's clock, so a pause never runs a team down mid-build."""
    tasks: list[asyncio.Task[Any]] = []
    waiting = None
    try:
        for index, job in enumerate(jobs):
            tasks.append(asyncio.create_task(build(index, job), name=f"build:{team_id}:{index}"))
        waiting = asyncio.gather(*tasks)
        await held_deadline(deadline).bound(asyncio.shield(waiting))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        joined = asyncio.gather(*tasks, return_exceptions=True)
        cancelled_again = False
        while not joined.done():
            try:
                await asyncio.shield(joined)
            except asyncio.CancelledError:
                cancelled_again = True
        # Retrieving this result also observes failures that raced cancellation.
        joined.result()
        if waiting is not None and waiting.done() and not waiting.cancelled():
            waiting.exception()
        if cancelled_again:
            raise asyncio.CancelledError


async def drain_owned(awaitable: Awaitable[Any]) -> Any:
    """Finish owned cleanup before propagating any repeated caller cancellation."""
    task = asyncio.ensure_future(awaitable)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


@asynccontextmanager
async def owned_events(events: AsyncIterator[Any], *, deadline: float | Callable[[], float], name: str):
    """Forward a stream in one context, with bounded buffering and joined cleanup.

    ``deadline`` is a loop time, or a callable giving it now (a :class:`~.run_control.HeldDeadline`, which a pause
    moves out); it is re-read every time a wait ends, so a wait already running sees the move."""
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1)

    def remaining() -> float:
        when = deadline() if callable(deadline) else deadline
        return when - asyncio.get_running_loop().time()

    async def produce() -> None:
        try:
            async for event in events:
                await queue.put(event)
        finally:
            close = getattr(events, "aclose", None)
            if close is not None:
                await close()

    producer = asyncio.create_task(produce(), name=name)
    next_event = None

    async def read():
        nonlocal next_event
        while True:
            left = remaining()
            if left <= 0:
                raise asyncio.TimeoutError
            if next_event is None:
                if not queue.empty():
                    yield queue.get_nowait()
                    continue
                if producer.done():
                    producer.result()
                    return
                next_event = asyncio.create_task(queue.get(), name=name + ":event")
            done, _ = await asyncio.wait({producer, next_event}, timeout=left, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                continue  # the deadline is read again: a pause may have moved it
            if next_event.done():
                event = next_event.result()
                next_event = None
                yield event
            else:
                producer.result()
                return

    completed_normally = False
    try:
        yield read()
        completed_normally = True
    finally:
        tasks = [producer] + ([next_event] if next_event is not None else [])
        for task in tasks:
            if not task.done():
                task.cancel()
        await drain_owned(asyncio.gather(*tasks, return_exceptions=True))
        if completed_normally and not producer.cancelled():
            producer.result()
