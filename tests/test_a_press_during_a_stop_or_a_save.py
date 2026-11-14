"""A press that lands while a stop waits or a save runs leaves the row, and what is saved, telling the truth."""

from __future__ import annotations

import asyncio
import copy
import functools
import json
import random
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests import runtime_plugin_fixture as fixture
from tests.plugin_page_fixture import (
    DEPENDANT,
    OFF,
    ON,
    PROVIDER,
    QUIET,
    ROUTES,
    hold_the_first_save,
    report_of,
    saved_choices,
    served,
)
from tests.plugin_view_fixture import runtime_with, state_of, until
from thomas.core.kernel import SelfStop
from thomas.server import runtime_plugins
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

HERE = __name__
press: Any = None  # what a row's own handler presses


async def _presses(_request: web.Request) -> web.Response:
    try:
        await press()
    except SelfStop as refused:
        return web.Response(text=str(refused))
    return web.Response(text="the press went through")


class _PressesFromInside:
    def __init__(self, name: str, *needs: str) -> None:
        self.name = name
        self.inject = ("web", *needs)

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx).router.add_get("/press", _presses)


presses_itself = _PressesFromInside("presses-itself")
presses_its_provider = _PressesFromInside("presses-its-provider", "thing")


@pytest.fixture(autouse=True)
def _nothing_left_from_the_last_test() -> None:
    views.reset()
    fixture.failures_left = 0
    fixture.cleaned_up.clear()


@pytest.mark.parametrize(
    ("rows", "pressed"),
    [
        pytest.param([("a", f"{HERE}:presses_itself", True)], "a", id="its-own-row"),
        pytest.param(
            [("a", PROVIDER, True), ("dep", f"{HERE}:presses_its_provider", True)], "a", id="a-row-it-depends-on"
        ),
    ],
)
def test_a_press_refused_from_inside_a_rows_own_work_changes_nothing(
    rows: list[tuple[str, str, bool]], pressed: str, tmp_path: Path
) -> None:
    """It would wait for itself. It used to save off first, so the row ran on and came back off at the next restart."""

    async def scenario() -> None:
        global press
        runtime = runtime_with(tmp_path, rows)
        runtime.load()
        runtime.mark_ready()
        press = functools.partial(runtime.turn_off, pressed)
        async with TestClient(TestServer(runtime.web.app)) as client:
            answer = await (await client.get("/press")).text()

            assert "cannot be stopped from inside its own work" in answer
            assert report_of(runtime, pressed)["enabled"] is True
            assert state_of(runtime, pressed) == "active"
            assert saved_choices(tmp_path) is None

    asyncio.run(scenario())


def test_on_is_refused_with_a_409_while_a_stop_is_waiting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving on here would leave it off now and bring it back at the next restart."""

    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        app = served(tmp_path, monkeypatch, ("a", ROUTES, True))
        runtime = app[APP_RUNTIME_PLUGINS]
        async with TestClient(TestServer(app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)
            turning_off = asyncio.create_task(client.post(OFF))
            await until(lambda: state_of(runtime, "a") == "unloading")

            refused = await client.post(ON)

            assert refused.status == 409
            assert report_of(runtime, "a")["enabled"] is False

            fixture.gate.set()
            await asyncio.gather(turning_off, running)

            assert state_of(runtime, "a") == "off"
            saved = tmp_path / "data" / "plugins" / "choices.json"
            assert json.loads(saved.read_text(encoding="utf-8")) == {"a": {"enabled": False}}

    asyncio.run(scenario())


def test_on_works_once_the_stop_has_finished(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        runtime = runtime_with(tmp_path, [("a", ROUTES, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)
            turning_off = asyncio.create_task(runtime.turn_off("a"))
            await until(lambda: state_of(runtime, "a") == "unloading")

            with pytest.raises(runtime_plugins.StillStopping):
                await runtime.turn_on("a")

            fixture.gate.set()
            await asyncio.gather(turning_off, running)

            assert (await runtime.turn_on("a"))["state"] == "active"

    asyncio.run(scenario())


def test_on_is_refused_for_a_row_held_up_by_its_providers_stop(tmp_path: Path) -> None:
    """The stop began at the provider, so this row's own switch has not been pressed, and it is going all the same."""

    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("provider", PROVIDER, True), ("dependant", DEPENDANT, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/slow"))
            await until(lambda: "slow began" in views.events)
            turning_off = asyncio.create_task(runtime.turn_off("provider"))
            await until(lambda: state_of(runtime, "dependant") == "unloading")
            saved = saved_choices(tmp_path)

            with pytest.raises(runtime_plugins.StillStopping):
                await runtime.turn_on("dependant")

            assert saved_choices(tmp_path) == saved

            views.release_slow.set()
            await asyncio.gather(turning_off, running)

    asyncio.run(scenario())


def test_an_on_that_lands_during_an_offs_save_stays_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nobody asked for what came up after that off to stop, and it would read off now and come back at the next restart."""

    async def scenario() -> None:
        saving, release = hold_the_first_save(monkeypatch)
        runtime = runtime_with(tmp_path, [("a", QUIET, False)])
        runtime.load()
        turning_off = asyncio.create_task(runtime.turn_off("a"))
        await until(saving.is_set)

        turning_on = asyncio.create_task(runtime.turn_on("a"))
        await until(lambda: state_of(runtime, "a") == "active")

        release.set()
        report = await turning_off

        assert (await turning_on)["state"] == "active"
        assert (report["enabled"], report["state"]) == (True, "active")
        assert saved_choices(tmp_path) == {"a": {"enabled": True}}
        assert len(runtime.kernel.mounted()) == 1

    asyncio.run(scenario())


def test_a_second_off_owns_the_stop_the_first_off_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first off found nothing to stop, so its ending can neither hide this wait nor be held up by it."""

    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        saving, release = hold_the_first_save(monkeypatch)
        runtime = runtime_with(tmp_path, [("a", ROUTES, False)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            first_off = asyncio.create_task(runtime.turn_off("a"))
            await until(saving.is_set)
            turning_on = asyncio.create_task(runtime.turn_on("a"))
            await until(lambda: state_of(runtime, "a") == "active")
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)
            second_off = asyncio.create_task(runtime.turn_off("a"))
            await until(lambda: state_of(runtime, "a") == "unloading")

            release.set()
            await asyncio.wait_for(first_off, timeout=30)

            assert state_of(runtime, "a") == "unloading"

            fixture.gate.set()
            await asyncio.gather(second_off, running, turning_on)

            assert state_of(runtime, "a") == "off"
            assert saved_choices(tmp_path) == {"a": {"enabled": False}}

    asyncio.run(scenario())


# -- saves land in the order you pressed --------------------------------------


# Long enough for a save running beside the first to land, which is the mistake. Saves in press order wait the whole of it
# with nothing to do, so a slow machine can only miss the mistake here, never fail a right answer.
A_BEAT = 0.2


def test_an_older_save_cannot_land_after_a_newer_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise the row reads on, the file says off, and off is what the next restart finds."""

    async def scenario() -> None:
        saving, release = hold_the_first_save(monkeypatch)
        runtime = runtime_with(tmp_path, [("a", QUIET, False)])
        runtime.load()
        turning_off = asyncio.create_task(runtime.turn_off("a"))
        await until(saving.is_set)
        turning_on = asyncio.create_task(runtime.turn_on("a"))
        await until(lambda: state_of(runtime, "a") == "active")
        await asyncio.wait({turning_on}, timeout=A_BEAT)

        release.set()
        await asyncio.gather(turning_off, turning_on)

        assert report_of(runtime, "a")["enabled"] is True
        assert saved_choices(tmp_path) == {"a": {"enabled": True}}

    asyncio.run(scenario())


def test_a_press_cancelled_while_its_save_waits_still_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It has already changed the row, so losing its save leaves the file behind what the row reads."""

    async def scenario() -> None:
        saving, release = hold_the_first_save(monkeypatch)
        runtime = runtime_with(tmp_path, [("a", QUIET, False)])
        runtime.load()
        turning_off = asyncio.create_task(runtime.turn_off("a"))
        await until(saving.is_set)
        turning_on = asyncio.create_task(runtime.turn_on("a"))
        await until(lambda: state_of(runtime, "a") == "active")

        turning_on.cancel()
        await asyncio.wait({turning_on})
        release.set()
        await turning_off
        await asyncio.get_running_loop().run_in_executor(runtime._saver, lambda: None)  # behind any save still queued

        assert saved_choices(tmp_path) == {"a": {"enabled": True}}

    asyncio.run(scenario())


def test_a_save_writes_what_its_own_press_left(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """What it writes is read on the event loop. Read in its thread, it would meet the next press changing the choices."""

    async def scenario() -> None:
        reached, release = threading.Event(), threading.Event()
        written: list[Any] = []

        def held(_path: Path, payload: Any) -> None:
            if not reached.is_set():
                reached.set()
                release.wait(timeout=30)
            written.append(copy.deepcopy(payload))

        monkeypatch.setattr(runtime_plugins, "write_json_atomic", held)
        runtime = runtime_with(tmp_path, [("a", QUIET, False), ("b", QUIET, False)])
        runtime.load()
        first = asyncio.create_task(runtime.turn_off("a"))
        await until(reached.is_set)
        second = asyncio.create_task(runtime.turn_off("b"))
        await asyncio.sleep(0)

        release.set()
        await asyncio.gather(first, second)

        assert written == [{"a": {"enabled": False}}, {"a": {"enabled": False}, "b": {"enabled": False}}]

    asyncio.run(scenario())


@pytest.mark.parametrize("seed", range(10))
def test_any_run_of_presses_leaves_the_file_agreeing_with_the_rows(
    seed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pick = random.Random(seed)
    write = runtime_plugins.write_json_atomic

    def slow(path: Path, payload: Any) -> None:
        read = copy.deepcopy(payload)
        time.sleep(pick.random() / 1000)
        write(path, read)

    async def scenario() -> None:
        monkeypatch.setattr(runtime_plugins, "write_json_atomic", slow)
        rows = ["a", "b", "c"]
        runtime = runtime_with(tmp_path, [(row, QUIET, True) for row in rows])
        runtime.load()

        for _ in range(9):
            await asyncio.gather(
                *((runtime.turn_on if pick.random() < 0.5 else runtime.turn_off)(pick.choice(rows)) for _ in range(5)),
                return_exceptions=True,  # an on that finds its row's stop waiting is refused, as you would see
            )

        enabled = {row["id"]: row["enabled"] for row in runtime.report()["rows"]}
        saved = saved_choices(tmp_path)
        assert {row: saved[row]["enabled"] for row in saved} == {row: enabled[row] for row in saved}

    asyncio.run(scenario())
