"""Rows writing one app key can stop in any order, and turning off leaves nothing behind."""

from __future__ import annotations

import asyncio
import itertools
from typing import Any

import pytest
from aiohttp import web

from tests.plugin_view_fixture import hosted, mount_on
from thomas.core.kernel import stop

KEY = web.AppKey("written_by_rows", str)
NOTHING = "nothing there"


async def _mount_writers(kernel: Any, names: tuple[str, ...]) -> dict[str, Any]:
    """Each row writes the key in turn, so the last name is the newest writer."""
    forks = {}
    for name in names:
        forks[name], view = mount_on(kernel)
        view[KEY] = name
    return forks


@pytest.mark.parametrize("before", [None, "there before any row"], ids=["absent-before", "there-before"])
@pytest.mark.parametrize("order", list(itertools.permutations("abc")), ids="".join)
def test_a_key_holds_its_newest_surviving_writer_whatever_order_they_stop(order: tuple[str, ...], before: Any) -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        if before is not None:
            app[KEY] = before
        forks = await _mount_writers(kernel, ("a", "b", "c"))
        still_here = ["a", "b", "c"]

        for name in order:
            await stop(forks[name])

            still_here.remove(name)
            expected = still_here[-1] if still_here else (before or NOTHING)
            assert app.get(KEY, NOTHING) == expected, f"after {name} stopped"

        assert kernel.root["web"].writers == {}

    asyncio.run(scenario())


def test_a_row_that_writes_again_is_the_newest_writer_again() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        first, view = mount_on(kernel)
        view[KEY] = "first"
        second, later = mount_on(kernel)
        later[KEY] = "second"
        view[KEY] = "first, again"

        await stop(second)
        assert app[KEY] == "first, again"

        await stop(first)
        assert KEY not in app

    asyncio.run(scenario())


def test_a_row_that_removed_the_key_gives_it_back() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        app[KEY] = "there before any row"
        first, view = mount_on(kernel)
        view[KEY] = "first"
        second, later = mount_on(kernel)
        del later[KEY]
        assert KEY not in app

        await stop(second)
        assert app[KEY] == "first"

        await stop(first)
        assert app[KEY] == "there before any row"

    asyncio.run(scenario())


def test_a_row_that_removed_the_key_keeps_it_removed_while_it_is_the_newest() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        first, view = mount_on(kernel)
        view[KEY] = "first"
        second, later = mount_on(kernel)
        del later[KEY]

        await stop(first)
        assert KEY not in app
        assert len(app) == 0  # a view reads as empty here, and the row behind it has still to give the key back
        assert KEY in kernel.root["web"].writers

        await stop(second)
        assert KEY not in app
        assert kernel.root["web"].writers == {}

    asyncio.run(scenario())


def test_what_the_server_wrote_between_two_rows_comes_back_when_the_later_row_stops() -> None:
    """The server is no row and never stops, so what it wrote outlives both, and an unwind must not clobber it."""

    async def scenario() -> None:
        app, kernel = hosted()
        first, view = mount_on(kernel)
        view[KEY] = "first"
        app._state[KEY] = "the server's"
        second, later = mount_on(kernel)
        later[KEY] = "second"

        await stop(second)
        assert app[KEY] == "the server's"

        await stop(first)
        assert app[KEY] == "the server's"
        assert kernel.root["web"].writers == {}

    asyncio.run(scenario())


def test_what_the_server_wrote_on_top_of_every_row_stays_on_top() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        first, view = mount_on(kernel)
        view[KEY] = "first"
        second, later = mount_on(kernel)
        later[KEY] = "second"
        app._state[KEY] = "the server's"

        await stop(second)
        assert app[KEY] == "the server's"

        await stop(first)
        assert app[KEY] == "the server's"

    asyncio.run(scenario())


def test_writing_one_key_over_and_over_keeps_one_record_of_it() -> None:
    """Handlers may write a key on every call, so a record for each write would grow for as long as the row is on."""
    _, kernel = hosted()
    _, view = mount_on(kernel)

    for value in range(50):
        view[KEY] = str(value)

    assert [written for _, written in kernel.root["web"].writers[KEY].writes] == ["49"]
