"""What the words of the media row promise about a job, and a row that fails.

``tests/test_turning_media_off_touches_only_its_routes.py`` holds the row's routes. This file holds what
``thomas.server.rows.media`` says about what runs. That dotted name, here, is how a check of the row finds this file.

A job is two tasks and a worker thread, and the row hands the route file ``ctx.task`` to start both tasks. A stop cancels
what ``ctx.task`` started while it waits, so off does not wait for a model. It cannot end the thread under the worker's
task, because Python cannot stop one, so the model goes on and nothing reads what it makes. With the job's task owned
and its worker's task left plain, the stop would wait for that thread with nothing counted and nothing on the page to
say why. With neither owned, nothing would stop or record the job, which would read running with the row off.

Everything runs in a process of its own, on the real server, the real task records and the real lock. Only the steps that
would load a model, send a request to Hugging Face or download a model are replaced, by ones that hold their thread.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.media_row_fixture import THROUGH_OFF_AND_ON
from tests.plugin_view_fixture import state_of
from tests.row_off_fixture import _in_a_process_of_its_own
from tests.row_proof_fixture import choose
from thomas.server import app_core
from thomas.server.routes import media_generation_routes
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "media"
LANES = "/api/media/lanes"


@pytest.fixture(scope="module")
def lived(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("media-lived")
    started, found = _in_a_process_of_its_own(THROUGH_OFF_AND_ON, ROW, [], folder, on=(ROW,))
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_both_tasks_of_a_job_belong_to_the_row(lived: dict[str, Any]) -> None:
    """Named by the row, which is how a stop knows them. A plain task would not be listed here."""
    assert lived["tasks_of_a_local_job"] == ["plugin:media:job", "plugin:media:local worker"]
    assert lived["tasks_of_a_provider_job"] == ["plugin:media:job", "plugin:media:provider worker"]


def test_off_answers_at_once_with_the_model_still_running(lived: dict[str, Any]) -> None:
    assert lived["running"] == "running"
    assert lived["off"]["state"] == "off"
    assert lived["worker_ended_when_off_answered"] is False
    assert lived["tasks_after_off"] == []


def test_a_job_off_stopped_is_recorded_and_never_reads_running(lived: dict[str, Any]) -> None:
    """The page asks the same question when the row is back, and a running answer here would spin for ever."""
    assert lived["record_after_off"] == {"state": "cancelled", "proof": "missing"}
    assert lived["asked_while_off"] == 404
    assert lived["asked_once_back_on"]["state"] == "cancelled"


def test_the_plugins_page_is_not_told_a_job_was_stopped(lived: dict[str, Any]) -> None:
    """A stop waits for no job, so nothing counts one, and the page reads plain Off. The row's words have to say it."""
    assert lived["off"]["stopped_partway"] is False


def test_new_work_on_a_local_model_waits_for_the_worker_off_could_not_end(lived: dict[str, Any]) -> None:
    """``_LOCAL_LOCK`` outlives off with the module, and must: a new lock would load a second model onto the GPU."""
    assert lived["second_while_the_first_worker_runs"] == "running"
    assert len(lived["began_while_the_first_worker_runs"]) == 1
    assert lived["lock_held"] is True
    assert lived["second"]["state"] == "completed"
    assert lived["second"]["deliverable"]["kind"] == "image"


def test_a_stopped_job_that_was_waiting_for_the_model_still_runs_and_reaches_nobody(lived: dict[str, Any]) -> None:
    """The row's words say so. Its worker is a thread waiting for a lock, and a stop cannot take it out of the queue."""
    assert len(lived["began_with_one_waiting"]) == 1
    assert lived["waiting_job_record_after_off"]["state"] == "cancelled"
    assert lived["the_waiting_job_ran_anyway"] is True
    assert lived["waiting_job_once_its_worker_ended"] == {"state": "cancelled", "proof": "missing"}


def test_what_a_stopped_job_goes_on_to_make_reaches_nobody(lived: dict[str, Any]) -> None:
    assert lived["first_left_a_file"] is True
    assert lived["first_once_its_worker_ended"]["state"] == "cancelled"
    assert lived["first_record_once_its_worker_ended"] == {"state": "cancelled", "proof": "missing"}


def test_a_request_to_the_provider_goes_on_after_off(lived: dict[str, Any]) -> None:
    assert lived["off_with_a_provider_job"] == "off"
    assert lived["provider_ended_when_off_answered"] is False
    assert lived["provider_record"]["state"] == "cancelled"


def test_a_download_holds_off_and_stop_now_leaves_it_running_and_unsaved(lived: dict[str, Any]) -> None:
    """The row's Stop now words, each one: it goes on downloading, the box fails, and your choice is not saved."""
    assert lived["held_by_a_download"]["state"] == "unloading"
    assert lived["held_by_a_download"]["waiting_for"] == 1
    assert lived["after_stop_now"]["state"] == "off"
    assert lived["after_stop_now"]["stopped_partway"] is True
    assert lived["the_download_request"] != 200
    assert lived["download_ended_at_stop_now"] is False
    assert lived["saved_after_the_download"]["video"] == ""


def test_a_job_started_as_off_was_pressed_is_still_recorded_as_stopped(lived: dict[str, Any]) -> None:
    """The request is allowed to end, so its job starts after the press. It must not be left reading running."""
    assert lived["held_by_a_start"]["waiting_for"] == 1
    assert lived["started_as_off_was_pressed"] == 202
    assert lived["its_record"]["state"] == "cancelled"


def test_what_you_chose_and_made_stays(lived: dict[str, Any]) -> None:
    assert lived["lanes_back_on"]["image"]["configured"] is True
    assert lived["lanes_back_on"]["music"]["configured"] is True
    assert lived["finished_file_with_the_row_off"] == 200


def test_the_start_key_leaves_with_the_row(lived: dict[str, Any]) -> None:
    assert (lived["start_key_on"], lived["start_key_off"]) == (True, False)


def test_a_registrar_that_fails_leaves_the_row_failed_with_nothing_on_the_table(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row that caught this would read active with no routes. The next press has to be able to bring it back."""
    working = media_generation_routes.setup_media_generation_routes

    def fails(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the registrar failed")

    choose(own_data_dir, on={ROW})
    monkeypatch.setattr(media_generation_routes, "setup_media_generation_routes", fails)

    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            assert state_of(runtime, ROW) == "failed"
            assert (await client.get(LANES)).status == 404
            monkeypatch.setattr(media_generation_routes, "setup_media_generation_routes", working)
            assert (await client.post(f"/api/plugins/thomas/{ROW}/off")).status == 200
            assert (await client.post(f"/api/plugins/thomas/{ROW}/on")).status == 200
            assert state_of(runtime, ROW) == "active"
            assert (await client.get(LANES)).status == 200

    asyncio.run(scenario())
