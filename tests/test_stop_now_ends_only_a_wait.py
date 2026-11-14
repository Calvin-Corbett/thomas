"""Stop now ends a stop that is waiting, reaches what holds it up, and changes nothing once the wait is over.

Only the server can tell whether a press cut anything, so each row says so in ``stopped_partway``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests import runtime_plugin_fixture as fixture
from tests.plugin_page_fixture import (
    DEPENDANT,
    HOOK_FAILS,
    OFF,
    PROVIDER,
    QUIET,
    ROUTES,
    hold_the_first_save,
    report_of,
    saved_choices,
    served,
)
from tests.plugin_view_fixture import runtime_with, state_of, until
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

HERE = __name__


@pytest.fixture(autouse=True)
def _nothing_left_from_the_last_test() -> None:
    views.reset()
    fixture.failures_left = 0
    fixture.cleaned_up.clear()


def test_stop_now_ends_a_wait_through_the_real_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        app = served(tmp_path, monkeypatch, ("a", ROUTES, True))
        runtime = app[APP_RUNTIME_PLUGINS]
        async with TestClient(TestServer(app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)
            turning_off = asyncio.create_task(client.post(OFF))
            await until(lambda: state_of(runtime, "a") == "unloading")

            answer = await asyncio.wait_for(client.post(f"{OFF}?force=1"), timeout=30)

            assert answer.status == 200
            assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
            assert state_of(runtime, "a") == "off"
            with pytest.raises(aiohttp.ClientError):  # force ended the work, so the connection ended with it
                await running

    asyncio.run(scenario())


def test_a_late_stop_now_leaves_a_running_row_and_its_work_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale press from another tab must not cut work the row took on after you turned it back on."""

    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        app = served(tmp_path, monkeypatch, ("a", ROUTES, True))
        runtime = app[APP_RUNTIME_PLUGINS]
        async with TestClient(TestServer(app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)

            answer = await client.post(f"{OFF}?force=1")

            assert answer.status == 200
            assert (await answer.json())["state"] == "active"
            assert not running.done()
            assert not (tmp_path / "data" / "plugins" / "choices.json").exists()

            fixture.gate.set()
            assert (await running).status == 200

    asyncio.run(scenario())


def test_a_late_stop_now_on_a_row_that_is_off_does_nothing(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("a", ROUTES, False)])
        runtime.load()

        report = await runtime.turn_off("a", force=True)

        assert report["state"] == "off"
        assert saved_choices(tmp_path) is None

    asyncio.run(scenario())


def test_stop_now_reaches_the_work_a_dependant_is_holding_the_stop_up_with(tmp_path: Path) -> None:
    """A stop waits for what uses this row first, so ending only this row's own work would leave it waiting."""

    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("provider", PROVIDER, True), ("dependant", DEPENDANT, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/slow"))
            await until(lambda: "slow began" in views.events)
            turning_off = asyncio.create_task(runtime.turn_off("provider"))
            await until(lambda: state_of(runtime, "dependant") == "unloading")

            await asyncio.wait_for(runtime.turn_off("provider", force=True), timeout=30)
            await asyncio.wait_for(turning_off, timeout=30)

            assert state_of(runtime, "provider") == "off"
            with pytest.raises(aiohttp.ClientError):  # force ended the work, so the connection ended with it
                await running

    asyncio.run(scenario())


def test_stop_now_on_a_row_held_up_by_its_providers_stop_ends_its_work(tmp_path: Path) -> None:
    """The row reads as stopping, so the page offers the button, even though this row was not the one pressed."""

    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("provider", PROVIDER, True), ("dependant", DEPENDANT, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/slow"))
            await until(lambda: "slow began" in views.events)
            turning_off = asyncio.create_task(runtime.turn_off("provider"))
            await until(lambda: state_of(runtime, "dependant") == "unloading")

            await runtime.turn_off("dependant", force=True)
            await asyncio.wait_for(turning_off, timeout=30)

            assert state_of(runtime, "provider") == "off"
            assert report_of(runtime, "dependant")["enabled"] is True  # it ended the wait, it did not turn this one off
            with pytest.raises(aiohttp.ClientError):
                await running

    asyncio.run(scenario())


# -- whether anything was cut ----------------------------------------------------


async def _held_at_the_gate() -> None:
    await fixture.gate.wait()


class _StuckIn:
    """A row with a step that holds its stop up, and no job for the row to count."""

    name = "stuck"
    inject = ()

    def __init__(self, add: str) -> None:
        self._add = add

    def apply(self, ctx: Any, config: Any) -> None:
        getattr(ctx, self._add)(_held_at_the_gate)


stuck_in_a_stop_step = _StuckIn("on_stopped")
stuck_in_a_drain_step = _StuckIn("on_drain")


def test_stop_now_says_it_cut_the_work_it_ended(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        app = served(tmp_path, monkeypatch, ("a", ROUTES, True))
        runtime = app[APP_RUNTIME_PLUGINS]
        async with TestClient(TestServer(app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)
            turning_off = asyncio.create_task(client.post(OFF))
            await until(lambda: state_of(runtime, "a") == "unloading")
            assert report_of(runtime, "a")["stopped_partway"] is False

            answer = await asyncio.wait_for(client.post(f"{OFF}?force=1"), timeout=30)

            assert (await answer.json())["stopped_partway"] is True
            await asyncio.wait_for(turning_off, timeout=30)
            assert (state_of(runtime, "a"), report_of(runtime, "a")["stopped_partway"]) == ("off", True)
            with pytest.raises(aiohttp.ClientError):
                await running

    asyncio.run(scenario())


def test_stop_now_that_lands_after_the_work_finished_cut_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window is up to a second, because the page only polls once a second."""

    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        app = served(tmp_path, monkeypatch, ("a", ROUTES, True))
        runtime = app[APP_RUNTIME_PLUGINS]
        async with TestClient(TestServer(app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)
            turning_off = asyncio.create_task(client.post(OFF))
            await until(lambda: state_of(runtime, "a") == "unloading")
            fixture.gate.set()
            await asyncio.gather(turning_off, running)

            answer = await (await client.post(f"{OFF}?force=1")).json()

            assert (answer["state"], answer["stopped_partway"]) == ("off", False)

    asyncio.run(scenario())


def test_stop_now_with_nothing_left_running_cut_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A press can find a row still stopping when no work is left, here while its choice saves."""

    async def scenario() -> None:
        saving, release = hold_the_first_save(monkeypatch)
        runtime = runtime_with(tmp_path, [("a", QUIET, True)])
        runtime.load()
        turning_off = asyncio.create_task(runtime.turn_off("a"))
        await until(saving.is_set)

        report = await runtime.turn_off("a", force=True)

        assert report["stopped_partway"] is False
        release.set()
        await turning_off
        assert report_of(runtime, "a")["stopped_partway"] is False

    asyncio.run(scenario())


def test_stop_now_does_not_count_the_work_of_a_row_it_has_nothing_to_do_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two stops can run side by side, and only what uses the row pressed is held up by its stop."""

    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("a", QUIET, True), ("b", ROUTES, True)])
        runtime.load()
        other = runtime._rows["b"].fork
        ended = asyncio.Event()

        async def job() -> None:
            async with other.ctx.busy():
                await ended.wait()

        running = asyncio.create_task(job())
        await asyncio.sleep(0)
        stopping_the_other = asyncio.create_task(runtime.turn_off("b"))
        await until(lambda: other.stopping)
        saving, release = hold_the_first_save(monkeypatch)
        turning_off = asyncio.create_task(runtime.turn_off("a"))
        await until(saving.is_set)

        report = await runtime.turn_off("a", force=True)

        assert report["stopped_partway"] is False
        assert not running.done()
        release.set()
        await turning_off
        ended.set()
        await asyncio.gather(running, stopping_the_other)

    asyncio.run(scenario())


def test_a_second_stop_now_cannot_take_back_what_the_first_one_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second tab can press it too, and by then nothing is left running for it to find."""

    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        saving, release = hold_the_first_save(monkeypatch)
        runtime = runtime_with(tmp_path, [("a", ROUTES, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)
            turning_off = asyncio.create_task(runtime.turn_off("a"))
            await until(saving.is_set)
            assert (await runtime.turn_off("a", force=True))["stopped_partway"] is True

            report = await runtime.turn_off("a", force=True)

            assert report["stopped_partway"] is True
            release.set()
            await turning_off
            with pytest.raises(aiohttp.ClientError):
                await running

    asyncio.run(scenario())


def test_a_late_stop_now_on_a_running_row_cut_nothing(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        runtime = runtime_with(tmp_path, [("a", ROUTES, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)

            assert (await runtime.turn_off("a", force=True))["stopped_partway"] is False

            fixture.gate.set()
            await running

    asyncio.run(scenario())


@pytest.mark.parametrize("step", ["stuck_in_a_stop_step", "stuck_in_a_drain_step"])
def test_a_step_stop_now_ended_counts_as_cut(step: str, tmp_path: Path) -> None:
    """Neither is a job the row counts, but each was running, and each ended before it finished."""

    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        runtime = runtime_with(tmp_path, [("a", f"{HERE}:{step}", True)])
        runtime.load()
        runtime.mark_ready()
        turning_off = asyncio.create_task(runtime.turn_off("a"))
        await until(lambda: state_of(runtime, "a") == "unloading")
        await asyncio.sleep(0.01)

        report = await asyncio.wait_for(runtime.turn_off("a", force=True), timeout=30)

        assert report["stopped_partway"] is True
        await asyncio.wait_for(turning_off, timeout=30)

    asyncio.run(scenario())


def test_stop_now_counts_the_work_a_dependant_was_holding_the_stop_up_with(tmp_path: Path) -> None:
    """The row pressed has nothing of its own running: the job was on the row that uses it."""

    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("provider", PROVIDER, True), ("dependant", DEPENDANT, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/slow"))
            await until(lambda: "slow began" in views.events)
            turning_off = asyncio.create_task(runtime.turn_off("provider"))
            await until(lambda: state_of(runtime, "dependant") == "unloading")
            assert report_of(runtime, "provider")["waiting_for"] == 0

            report = await asyncio.wait_for(runtime.turn_off("provider", force=True), timeout=30)

            assert report["stopped_partway"] is True
            await asyncio.wait_for(turning_off, timeout=30)
            with pytest.raises(aiohttp.ClientError):
                await running

    asyncio.run(scenario())


def test_stop_now_on_a_row_held_up_by_its_providers_stop_counts_its_own_work(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("provider", PROVIDER, True), ("dependant", DEPENDANT, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/slow"))
            await until(lambda: "slow began" in views.events)
            turning_off = asyncio.create_task(runtime.turn_off("provider"))
            await until(lambda: state_of(runtime, "dependant") == "unloading")

            report = await runtime.turn_off("dependant", force=True)

            assert report["stopped_partway"] is True
            await asyncio.wait_for(turning_off, timeout=30)
            with pytest.raises(aiohttp.ClientError):
                await running

    asyncio.run(scenario())


def test_a_stop_that_ends_by_itself_never_says_it_was_cut(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        runtime = runtime_with(tmp_path, [("a", ROUTES, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)
            turning_off = asyncio.create_task(runtime.turn_off("a"))
            await until(lambda: state_of(runtime, "a") == "unloading")

            fixture.gate.set()

            assert (await turning_off)["stopped_partway"] is False
            await running

    asyncio.run(scenario())


def test_a_cut_is_about_the_last_stop_and_no_later_one(tmp_path: Path) -> None:
    """On again takes it away, and a later stop that finishes by itself must not inherit the sentence."""

    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        runtime = runtime_with(tmp_path, [("a", ROUTES, True)])
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)
            turning_off = asyncio.create_task(runtime.turn_off("a"))
            await until(lambda: state_of(runtime, "a") == "unloading")
            await runtime.turn_off("a", force=True)
            await turning_off
            with pytest.raises(aiohttp.ClientError):
                await running
            assert report_of(runtime, "a")["stopped_partway"] is True

            assert (await runtime.turn_on("a"))["stopped_partway"] is False
            assert (await runtime.turn_off("a"))["stopped_partway"] is False

    asyncio.run(scenario())


def test_leave_it_off_after_a_cut_try_again_says_nothing_was_cut(tmp_path: Path) -> None:
    """Stop now can end the clearing away of a failure. The row then fails again, and you leave it off: no stop ran."""

    async def scenario() -> None:
        fixture.gate = asyncio.Event()
        fixture.failures_left = 1
        runtime = runtime_with(tmp_path, [("a", HOOK_FAILS, True)])
        runtime.load()
        runtime.mark_ready()
        async with TestClient(TestServer(runtime.web.app)) as client:
            await until(lambda: state_of(runtime, "a") == "failed")
            running = asyncio.create_task(client.get("/fixture/slow"))
            await until(lambda: report_of(runtime, "a")["waiting_for"] == 1)
            fixture.failures_left = 1
            trying = asyncio.create_task(runtime.turn_on("a"))
            await until(lambda: state_of(runtime, "a") == "unloading")
            assert (await runtime.turn_off("a", force=True))["stopped_partway"] is True
            await asyncio.wait_for(trying, timeout=30)
            await asyncio.gather(running, return_exceptions=True)
            await until(lambda: state_of(runtime, "a") == "failed")

            assert (await runtime.turn_off("a"))["stopped_partway"] is False

    asyncio.run(scenario())
