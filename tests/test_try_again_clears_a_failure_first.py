"""Turning a failed row on tries again, and what the failed one still holds is finished and cleaned up first."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests import runtime_plugin_fixture as fixture
from tests.plugin_page_fixture import FAILS_STARTING, HOOK_FAILS, report_of, saved_choices
from tests.plugin_view_fixture import runtime_with, state_of, until


@pytest.fixture(autouse=True)
def _nothing_left_from_the_last_test() -> None:
    views.reset()
    fixture.failures_left = 0
    fixture.cleaned_up.clear()


def test_try_again_starts_a_row_that_failed_at_startup(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture.failures_left = 1
        runtime = runtime_with(tmp_path, [("bad", FAILS_STARTING, True)])
        runtime.load()
        runtime.mark_ready()
        assert state_of(runtime, "bad") == "failed"

        report = await runtime.turn_on("bad")

        assert report["state"] == "active"
        assert report["error"] == ""
        assert len(runtime.kernel._forks) == 1  # the failed one is not left behind on the kernel

    asyncio.run(scenario())


def test_try_again_that_fails_again_says_why_and_can_be_pressed_again(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture.failures_left = 2
        runtime = runtime_with(tmp_path, [("bad", FAILS_STARTING, True)])
        runtime.load()
        runtime.mark_ready()

        report = await runtime.turn_on("bad")

        assert report["state"] == "failed"
        assert "the port is taken" in report["error"]

        assert (await runtime.turn_on("bad"))["state"] == "active"

    asyncio.run(scenario())


def test_try_again_on_a_row_still_plugged_in_finishes_its_work_and_cleans_up_first(tmp_path: Path) -> None:
    """A hook added once a row is live can fail with routes up and a cleanup owed. Mounting over that would claim them."""

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

            trying = asyncio.create_task(runtime.turn_on("a"))
            await until(lambda: state_of(runtime, "a") == "unloading")

            assert not running.done()
            assert fixture.cleaned_up == []

            fixture.gate.set()
            report = await trying

            assert report["state"] == "active"
            assert (await running).status == 200
            assert fixture.cleaned_up == ["cleaned up"]
            assert len(runtime.kernel._forks) == 1
            assert (await client.get("/fixture/slow")).status == 200  # the new mount's route, not the one that left

    asyncio.run(scenario())


def test_off_pressed_while_try_again_clears_the_failure_leaves_it_off(tmp_path: Path) -> None:
    """Off must be able to take back an on that has not landed yet, and the choice is saved before the wait ends."""

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
            trying = asyncio.create_task(runtime.turn_on("a"))
            await until(lambda: state_of(runtime, "a") == "unloading")

            report = await runtime.turn_off("a")

            assert report["enabled"] is False
            assert saved_choices(tmp_path) == {"a": {"enabled": False}}

            fixture.gate.set()
            await asyncio.gather(trying, running)

            assert state_of(runtime, "a") == "off"
            assert saved_choices(tmp_path) == {"a": {"enabled": False}}

    asyncio.run(scenario())
