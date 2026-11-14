"""The Praxis row with a Build run going: off waits for it, the run's helpers keep their route, and Stop now loses nothing.

A Build run's helpers call the channel route for as long as the run lasts, so a stop that took the route away at once
would hand them a 404 in the middle of their work. The row keeps the route while it waits, counts each open channel as its
work, and on Stop now suspends every channel with its progress in the run journal. Turning the row back on takes each
interrupted run up again from the journal, before the restart pass reads the report.

These are the proofs of ``thomas.server.rows.praxis`` and ``thomas.server.praxis.run_channel`` for a stop. The route
and its words are in ``tests/test_turning_praxis_off_touches_only_its_routes.py``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests import praxis_row_fixture as fx
from tests.praxis_row_fixture import OFF, ON, SETTINGS
from thomas.server import app_core
from thomas.server.app_keys import APP_PRAXIS_RECOVERY_REPORT, APP_PRAXIS_RUN_CHANNELS
from thomas.server.praxis import launch
from thomas.server.praxis.recovery import PraxisRunJournal
from thomas.server.routes.praxis_run_routes import register_praxis_run_routes


@pytest.fixture
def journal_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return fx.journal_folder(tmp_path, monkeypatch)


def test_off_waits_for_an_open_run_and_its_helpers_keep_the_route_until_it_ends(
    journal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)

    async def scenario() -> None:
        client = await fx.server_with_the_row_on(journal_root)
        try:
            app = client.app
            channel = fx.open_run(app, journal_root)
            registry = app[APP_PRAXIS_RUN_CHANNELS]
            await asyncio.sleep(0.05)

            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: fx.row_of(app)["state"] == "unloading"), timeout=30)
            await asyncio.sleep(0.2)

            assert fx.row_of(app)["waiting_for"] == 1
            assert not turning_off.done()
            assert await fx.call_status(client, channel) == 200  # the route is kept for the run's helpers

            await registry.suspend("r1")  # what the run's end does

            assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
            assert fx.row_of(app)["state"] == "off"
            assert await fx.call_status(client, channel) == 404
            assert APP_PRAXIS_RUN_CHANNELS not in app
        finally:
            await client.close()

    asyncio.run(scenario())


def test_stop_now_keeps_the_run_in_the_journal_and_turning_on_takes_it_up_again(
    journal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)
    resumed: list[str] = []

    async def scenario() -> None:
        client = await fx.server_with_the_row_on(journal_root)
        try:
            app = client.app
            channel = fx.open_run(app, journal_root)
            handles = await channel.spawn([{"kind": "review", "title": "Look", "brief": "Inspect A"}])
            await asyncio.sleep(0.05)
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: fx.row_of(app)["state"] == "unloading"), timeout=30)
            assert fx.row_of(app)["waiting_for"] == 1

            assert (await asyncio.wait_for(client.post(f"{OFF}?force=1"), timeout=60)).status == 200

            assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
            assert fx.row_of(app)["state"] == "off"
            assert APP_PRAXIS_RUN_CHANNELS not in app
            assert APP_PRAXIS_RECOVERY_REPORT not in app
            journal = PraxisRunJournal(journal_root / "journal" / "praxis" / "runs.sqlite3")
            assert journal.interrupted_runs() == ["r1"]  # the run is not lost

            monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_finishes(resumed))
            assert (await asyncio.wait_for(client.post(ON), timeout=60)).status == 200

            assert app[APP_PRAXIS_RECOVERY_REPORT]["resumed"] == [
                {"run_id": "r1", "conversation_id": "conv-1", "agents": 1}
            ]
            recovered = app[APP_PRAXIS_RUN_CHANNELS]._runs["r1"]
            assert recovered.token != channel.token
            await recovered._tasks[handles[0]["agent_id"]]
            assert resumed == [handles[0]["agent_id"]]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_run_a_restart_interrupted_is_in_the_report_the_moment_the_server_is_up(
    journal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The restart pass reads this report straight after the rows start, so the scan cannot be a task that follows."""
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)
    resumed: list[str] = []

    async def scenario() -> None:
        before = web.Application()
        earlier = register_praxis_run_routes(before)
        launch.prepare_launch(
            before, SETTINGS, journal_root / "project", "r1", "request", {}, 8899, conversation_id="c"
        )
        handles = await earlier._runs["r1"].spawn([{"kind": "review", "title": "Look", "brief": "Inspect A"}])
        await earlier.suspend("r1")

        monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_finishes(resumed))
        client = TestClient(TestServer(app_core.create_app(views.config_in(journal_root))))
        await client.start_server()  # returns once on_startup has ended, which is where the restart pass begins
        try:
            report = client.app.get(APP_PRAXIS_RECOVERY_REPORT)
            assert report == {"resumed": [{"run_id": "r1", "conversation_id": "c", "agents": 1}], "skipped": []}
            await client.app[APP_PRAXIS_RUN_CHANNELS]._runs["r1"]._tasks[handles[0]["agent_id"]]

            # Its helper has finished, so the recovered run no longer holds the switch.
            await asyncio.wait_for(views.until(lambda: fx.row_of(client.app)["state"] == "active"), timeout=30)
            assert (await asyncio.wait_for(client.post(OFF), timeout=30)).status == 200
            assert fx.row_of(client.app)["state"] == "off"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_run_taken_up_after_a_restart_holds_the_switch_while_its_helper_is_alive(
    journal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the hold in ``adopt`` the press below finishes at once and drops the helper's route under it."""
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)

    async def scenario() -> None:
        before = web.Application()
        earlier = register_praxis_run_routes(before)
        launch.prepare_launch(
            before, SETTINGS, journal_root / "project", "r1", "request", {}, 8899, conversation_id="c"
        )
        await earlier._runs["r1"].spawn([{"kind": "review", "title": "Look", "brief": "Inspect A"}])
        await earlier.suspend("r1")

        client = TestClient(TestServer(app_core.create_app(views.config_in(journal_root))))
        await client.start_server()  # takes r1 up again, and its helper waits for ever
        try:
            await asyncio.wait_for(views.until(lambda: fx.row_of(client.app)["state"] == "active"), timeout=30)
            assert "r1" in client.app[APP_PRAXIS_RUN_CHANNELS]._runs
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: fx.row_of(client.app)["state"] == "unloading"), timeout=30)
            await asyncio.sleep(0.3)
            assert fx.row_of(client.app)["waiting_for"] == 1  # the recovered run is waited for
            assert not turning_off.done()
            assert (await asyncio.wait_for(client.post(f"{OFF}?force=1"), timeout=60)).status == 200
            await asyncio.wait_for(turning_off, timeout=30)
        finally:
            await client.close()

    asyncio.run(scenario())
