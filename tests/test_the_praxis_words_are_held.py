"""The Build run channel row's words, a sentence at a time, each with the test that shows it.

The words are what the Plugins page tells you, so none of them lands on the strength of having been true once. Each was
also read off a real browser on a scratch server with a run held open: the page said "Turning off..." and "Finishing 1
job first", Stop now ended the wait, and turning it on took the run up again. What a browser cannot see, because no page
calls the route, is shown here: what a run starts with when the row is off, what its team meets, what a restart reports,
and what Stop now does to a writer.

Proofs of ``thomas.server.rows.praxis``. The routes are in ``tests/test_turning_praxis_off_touches_only_its_routes.py`` and
a run going in ``tests/test_turning_praxis_off_with_a_run_going.py``.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient

from tests import plugin_view_fixture as views
from tests import praxis_row_fixture as fx
from tests.praxis_row_fixture import OFF, ON, SETTINGS
from tests.row_proof_fixture import ROOT, ROWS
from thomas.forge.anvil.run_channel_client import RunChannelClient
from thomas.server.app_keys import APP_PRAXIS_RUN_CHANNELS
from thomas.server.praxis import launch
from thomas.server.praxis.recovery import PraxisRunJournal
from thomas.server.praxis.run_channel import RunChannel


@pytest.fixture
def journal_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return fx.journal_folder(tmp_path, monkeypatch)


HERE = "tests/test_the_praxis_words_are_held.py"
OFF_RUNNING = "tests/test_turning_praxis_off_with_a_run_going.py"
ROUTES = "tests/test_turning_praxis_off_touches_only_its_routes.py"
CHANNEL = "tests/test_praxis_run_channel.py"
DELETING = "tests/test_a_build_team_can_delete_a_file.py"
WORDS = {
    "Lets a Build run call back into Thomas while it works.": (
        HERE,
        "test_a_team_reaches_the_channel_while_the_row_is_on",
    ),
    "Through it, a Build team starts readers, reviewers and checkers, waits for them, and deletes files in its own "
    "project folder when it may edit.": (
        (CHANNEL, "test_cited_plan_waits_for_dependencies_and_refuses_uncited_work"),
        (DELETING, "test_a_file_in_the_project_is_really_deleted_and_the_run_history_shows_it"),
    ),
    "It also keeps what those helpers were doing, so Thomas can take them up again after a restart.": (
        OFF_RUNNING,
        "test_a_run_a_restart_interrupted_is_in_the_report_the_moment_the_server_is_up",
    ),
    "No page in the sidebar shows this, and no page calls it.": (ROUTES, "test_no_page_of_ours_calls_this_route"),
    "Once this is off, a Build run that starts gets no channel: its team cannot start readers, reviewers or checkers "
    "or delete files, and the run carries on without them.": (
        HERE,
        "test_with_the_row_off_a_run_starts_with_no_channel",
    ),
    "While Thomas is still waiting for a run to end, a run that starts gets a channel as usual and Thomas waits for "
    "that one too, so a steady chain of runs can keep it waiting.": (
        HERE,
        "test_a_run_that_starts_during_the_wait_gets_a_channel_and_is_waited_for",
    ),
    "Nothing you normally use changes at that moment.": (ROUTES, "test_no_page_of_ours_calls_this_route"),
    "A run that is already going keeps its channel until it ends.": (
        OFF_RUNNING,
        "test_off_waits_for_an_open_run_and_its_helpers_keep_the_route_until_it_ends",
    ),
    "If one is going when you turn this off, Thomas waits for it, which can take many hours, and its calls still work "
    "while it waits.": (OFF_RUNNING, "test_off_waits_for_an_open_run_and_its_helpers_keep_the_route_until_it_ends"),
    "After a restart with this off, Thomas has nothing to report about the helpers of a run the restart interrupted, "
    "and nothing takes them up again.": (HERE, "test_with_the_row_off_thomas_reports_nothing_about_an_interrupted_run"),
    "What was saved for those runs stays saved, and turning this back on takes up the ones that were reading, "
    "reviewing or checking.": (
        OFF_RUNNING,
        "test_stop_now_keeps_the_run_in_the_journal_and_turning_on_takes_it_up_again",
    ),
    "Stop now ends the wait.": (
        OFF_RUNNING,
        "test_stop_now_keeps_the_run_in_the_journal_and_turning_on_takes_it_up_again",
    ),
    "Every open run's helpers are stopped where they are and saved, so turning this back on takes up again the ones "
    "that were reading, reviewing or checking.": (
        OFF_RUNNING,
        "test_stop_now_keeps_the_run_in_the_journal_and_turning_on_takes_it_up_again",
    ),
    "A helper that was writing files is marked interrupted and needs a new Build run.": (
        HERE,
        "test_stop_now_marks_a_writer_interrupted",
    ),
    "While the stop is finishing, a Build run that starts may fail to start.": (
        HERE,
        "test_a_run_that_starts_while_the_stop_is_finishing_fails_to_start",
    ),
    "A Build run that is already going is not stopped, but its calls to Thomas fail after that.": (
        HERE,
        "test_a_teams_call_fails_with_a_refusal_it_can_read_once_the_row_is_off",
    ),
    "So a writer in it that has not started cannot start, and one that had already put its file in place may still "
    "be marked as failed.": (HERE, "test_a_writers_start_and_report_both_fail_once_the_row_is_off"),
}


def _sentences() -> list[str]:
    row = next(row for row in ROWS if row.id == "praxis").config["words"]
    return [part for key in ("about", "off_means", "stop_now") for part in re.split(r"(?<=\.)\s+", row[key])]


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    """A new, changed or dropped sentence fails here until the list has it with a test."""
    assert _sentences() == list(WORDS)
    for sentence, shown in WORDS.items():
        pairs = (shown,) if isinstance(shown[0], str) else shown
        for path, name in pairs:
            assert f"def {name}(" in (ROOT / path).read_text(encoding="utf-8"), (sentence, name)


def _launch(app: web.Application, root: Path, env: dict[str, str]) -> Any:
    return launch.prepare_launch(app, SETTINGS, root / "project", "r1", "request", env, 8899, conversation_id="c")[1]


def test_a_team_reaches_the_channel_while_the_row_is_on(journal_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)

    async def scenario() -> None:
        client = await fx.server_with_the_row_on(journal_root)
        try:
            env: dict[str, str] = {}
            assert _launch(client.app, journal_root, env) is client.app[APP_PRAXIS_RUN_CHANNELS]
            assert env["THOMAS_RUN_CHANNEL_URL"] == "http://127.0.0.1:8899"
            token = env["THOMAS_RUN_CHANNEL_TOKEN"]
            team = RunChannelClient(base_url=f"http://127.0.0.1:{client.server.port}", run_id="r1", token=token)
            assert (await team.call("status", {}))["ok"] is True
        finally:
            await client.close()

    asyncio.run(scenario())


def test_with_the_row_off_a_run_starts_with_no_channel(journal_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)

    async def scenario() -> None:
        client = await fx.server_with_the_row_on(journal_root)
        try:
            assert (await asyncio.wait_for(client.post(OFF), timeout=30)).status == 200
            env: dict[str, str] = {}
            assert _launch(client.app, journal_root, env) is None
            assert not {key for key in env if "RUN_CHANNEL" in key}
            for key in ("THOMAS_RUN_CHANNEL_URL", "THOMAS_CODE_RUN_ID", "THOMAS_RUN_CHANNEL_TOKEN"):
                monkeypatch.delenv(key, raising=False)
            for key, value in env.items():
                monkeypatch.setenv(key, value)
            assert RunChannelClient.from_environment() is None  # so no tools are offered to the team
        finally:
            await client.close()

    asyncio.run(scenario())


async def _interrupted_run(client: TestClient, root: Path) -> None:
    """A run in the journal that a restart interrupted, as the first test of the Praxis recovery leaves one."""
    channel = fx.open_run(client.app, root)
    await channel.spawn([{"kind": "review", "title": "Look", "brief": "Inspect A"}])
    await client.app[APP_PRAXIS_RUN_CHANNELS].suspend("r1")


def test_with_the_row_off_thomas_reports_nothing_about_an_interrupted_run(
    journal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the Build page reads is this answer, so with the row off it has no helpers to list."""
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)
    ask = "/api/evolve/agent/status?conversation_id=conv-1"

    async def scenario() -> None:
        client = await fx.server_with_the_row_on(journal_root)
        try:
            await _interrupted_run(client, journal_root)
            assert (await asyncio.wait_for(client.post(OFF), timeout=30)).status == 200
            assert (await asyncio.wait_for(client.post(ON), timeout=30)).status == 200
            assert (await (await client.get(ask)).json())["praxis_recovered"]["run_id"] == "r1"

            # The run it took up again holds the switch, so this is a press and then a Stop now.
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: fx.row_of(client.app)["state"] == "unloading"), timeout=30)
            assert (await asyncio.wait_for(client.post(f"{OFF}?force=1"), timeout=60)).status == 200
            await asyncio.wait_for(turning_off, timeout=30)
            assert fx.row_of(client.app)["state"] == "off"
            answer = await (await client.get(ask)).json()
            assert "praxis_recovered" not in answer
            assert (await (await client.get("/api/evolve/agent/status")).json())["praxis_recovered_runs"] == []
            assert PraxisRunJournal(journal_root / "journal" / "praxis" / "runs.sqlite3").interrupted_runs() == ["r1"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_stop_now_marks_a_writer_interrupted(journal_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)

    async def scenario() -> None:
        client = await fx.server_with_the_row_on(journal_root)
        try:
            channel = fx.open_run(client.app, journal_root)
            writer = await channel.admit_external_builder(plan_id="p1", title="Write", brief="Do it", path="a.txt")
            await asyncio.sleep(0.05)
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: fx.row_of(client.app)["state"] == "unloading"), timeout=30)
            assert (await asyncio.wait_for(client.post(f"{OFF}?force=1"), timeout=60)).status == 200
            await asyncio.wait_for(turning_off, timeout=30)

            saved = PraxisRunJournal(journal_root / "journal" / "praxis" / "runs.sqlite3").load("r1")
            states = {child["agent_id"]: child["state"] for child in saved["children"]}
            assert states == {writer["agent_id"]: "interrupted"}
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_teams_call_fails_with_a_refusal_it_can_read_once_the_row_is_off(
    journal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)

    async def scenario() -> None:
        client = await fx.server_with_the_row_on(journal_root)
        try:
            env: dict[str, str] = {}
            _launch(client.app, journal_root, env)
            team = RunChannelClient(
                base_url=f"http://127.0.0.1:{client.server.port}", run_id="r1", token=env["THOMAS_RUN_CHANNEL_TOKEN"]
            )
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: fx.row_of(client.app)["state"] == "unloading"), timeout=30)
            assert (await team.call("status", {}))["ok"] is True  # still answered while it waits
            await asyncio.wait_for(client.post(f"{OFF}?force=1"), timeout=60)
            await asyncio.wait_for(turning_off, timeout=30)

            with pytest.raises(RuntimeError, match="HTTP 404"):
                await team.call("status", {})
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_run_that_starts_during_the_wait_gets_a_channel_and_is_waited_for(
    journal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)

    async def scenario() -> None:
        client = await fx.server_with_the_row_on(journal_root)
        try:
            fx.open_run(client.app, journal_root, "r1")
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: fx.row_of(client.app)["state"] == "unloading"), timeout=30)
            env: dict[str, str] = {}
            late = launch.prepare_launch(
                client.app, SETTINGS, journal_root / "project", "r2", "request", env, 8899, conversation_id="c"
            )[1]
            assert late is client.app[APP_PRAXIS_RUN_CHANNELS]
            assert env["THOMAS_RUN_CHANNEL_TOKEN"]  # it got a channel
            registry = client.app[APP_PRAXIS_RUN_CHANNELS]
            await registry.suspend("r1")
            await asyncio.sleep(0.3)
            assert not turning_off.done()  # r2 is still being waited for
            assert fx.row_of(client.app)["state"] == "unloading"
            assert fx.row_of(client.app)["waiting_for"] == 1
            await registry.suspend("r2")
            assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_run_that_starts_while_the_stop_is_finishing_fails_to_start(
    journal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)
    real_suspend = RunChannel.suspend

    async def slow_suspend(self: RunChannel) -> None:
        await asyncio.sleep(2)
        await real_suspend(self)

    monkeypatch.setattr(RunChannel, "suspend", slow_suspend)

    async def scenario() -> None:
        client = await fx.server_with_the_row_on(journal_root)
        try:
            fx.open_run(client.app, journal_root, "r1")
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: fx.row_of(client.app)["state"] == "unloading"), timeout=30)
            forced = asyncio.create_task(client.post(f"{OFF}?force=1"))
            await asyncio.sleep(1)
            assert not forced.done()  # the stop is still busy suspending r1
            with pytest.raises(Exception):  # the registry's own refusal, whatever its class
                fx.open_run(client.app, journal_root, "r2")
            assert (await asyncio.wait_for(forced, timeout=60)).status == 200
            await asyncio.wait_for(turning_off, timeout=30)
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_writers_start_and_report_both_fail_once_the_row_is_off(
    journal_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scheduler makes both calls for each writer, so a stop between them fails the one that follows."""
    monkeypatch.setattr(launch, "build_dispatching_child_runner", fx.runner_that_waits)

    async def scenario() -> None:
        client = await fx.server_with_the_row_on(journal_root)
        try:
            env: dict[str, str] = {}
            _launch(client.app, journal_root, env)
            team = RunChannelClient(
                base_url=f"http://127.0.0.1:{client.server.port}", run_id="r1", token=env["THOMAS_RUN_CHANNEL_TOKEN"]
            )
            plan = {"plan_id": "p1", "title": "Write", "brief": "Do it", "path": "a.txt"}
            admitted = await team.call("admit_builder", plan)
            agent_id = admitted["agent"]["agent_id"]
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: fx.row_of(client.app)["state"] == "unloading"), timeout=30)
            await asyncio.wait_for(client.post(f"{OFF}?force=1"), timeout=60)
            await asyncio.wait_for(turning_off, timeout=30)

            with pytest.raises(RuntimeError, match="HTTP 404"):
                await team.call("admit_builder", {**plan, "plan_id": "p2"})
            with pytest.raises(RuntimeError, match="HTTP 404"):
                await team.call("report_builder", {"agent_id": agent_id, "event": {"type": "integrated"}})
        finally:
            await client.close()

    asyncio.run(scenario())
