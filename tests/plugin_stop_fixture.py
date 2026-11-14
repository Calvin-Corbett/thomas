"""What the tests of a plugin stopping share: a plugin that does nothing, and small waits."""

from __future__ import annotations

import asyncio


def quiet(ctx, config):
    return None


quiet.name = "quiet"


async def turns(count: int = 5) -> None:
    """Hand the event loop a few turns, so a stop that was woken has run as far as it will."""
    for _ in range(count):
        await asyncio.sleep(0)


async def ignores_being_cancelled(release: asyncio.Event) -> None:
    """Code a stop cannot end. It must be released before the test ends, or ``asyncio.run`` waits for it for ever."""
    while not release.is_set():
        try:
            await release.wait()
        except asyncio.CancelledError:
            pass


def providing(name, *sets, order, inject=()):
    """A plugin that provides ``sets``, and says when its stop step ran."""

    def plugin(ctx, config):
        async def clean_up() -> None:
            order.append(f"{name} cleaned up")

        for service in sets:
            ctx.set(service, name)
        ctx.on_stopped(clean_up)

    plugin.name = name
    plugin.inject = inject
    return plugin


async def ends(stopping: asyncio.Task) -> None:
    """Wait for a stop that must end without help. The bound only turns a hang into a failure."""
    await asyncio.wait({stopping}, timeout=10)
    assert stopping.done(), "the stop is still waiting"
