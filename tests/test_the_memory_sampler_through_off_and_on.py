"""What the words of the machine_capacity row promise: a run is watched only while it is on, and the limit stays.

``tests/test_turning_machine_capacity_off_touches_only_its_routes.py`` holds the row's routes. This file holds the rest of
what ``thomas.server.rows.machine_capacity`` says or leans on: what happens to a run, to the saved limit and to a stop.
That dotted name, here, is how a check of the row finds this file.

Each test starts a real server with only this row on, on its own data folder, so the sampler's hooks run on a view of the
real app and read the real run registry. The saved file is read only once the write that is being waited for is done,
because polling it could make a save fail on Windows.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.plugin_view_fixture import state_of, until
from tests.row_proof_fixture import ROOT, choose
from thomas.core import machine_capacity as mc
from thomas.core import step_log, step_report
from thomas.server import app_core
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "machine_capacity"
SAMPLER_TASK = f"plugin:{ROW}:memory sampler"
KEYS = {mc._APP_PROFILE_SNAPSHOT, mc._APP_SAMPLER_TASK, mc._APP_SAMPLER_PEAKS}
A_RUN = {"c1": {"session": {"proc": SimpleNamespace(pid=os.getpid()), "run_id": "a-run"}}}


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices and the limit both live in the data dir. Only this row is on, so its tasks are the ones here."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_STEP_LOG_DIR", str(tmp_path / "data" / "metrics"))
    monkeypatch.setattr(mc, "_SAMPLE_INTERVAL_SECONDS", 0.01)
    choose(tmp_path / "data", on={ROW})
    return tmp_path / "data"


@pytest.fixture
def peaks(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Each peak the sampler saved, added once its save has ended."""
    saved: list[float] = []
    record = mc.record_run_peak

    def recording(peak_mb: float) -> None:
        record(peak_mb)
        saved.append(peak_mb)

    monkeypatch.setattr(mc, "record_run_peak", recording)
    return saved


def _runs(app: web.Application, runs: dict[str, Any]) -> None:
    app._state[mc._RUN_REGISTRY_KEY] = runs  # the app froze at startup, so as the route that adds a run writes it


def _saved(data: Path) -> dict[str, Any]:
    return json.loads((data / "machine_capacity.json").read_text(encoding="utf-8"))


async def _measure_one_run(app: web.Application, peaks: list[float]) -> float:
    """A run is seen, then leaves, and what it reached is saved."""
    count = len(peaks)
    _runs(app, A_RUN)
    await until(lambda: "a-run" in app[mc._APP_SAMPLER_PEAKS])
    _runs(app, {})
    await until(lambda: len(peaks) > count)
    return peaks[-1]


async def _active(app: web.Application) -> Any:
    runtime = app[APP_RUNTIME_PLUGINS]
    await until(lambda: state_of(runtime, ROW) != "loading")
    assert state_of(runtime, ROW) == "active", runtime.report()
    return runtime


def test_a_run_is_watched_through_the_row_and_its_peak_is_saved(
    tmp_path: Path, own_data_dir: Path, peaks: list[float]
) -> None:
    """The sampler's own task, on the real run registry, read through the row's view of the app."""

    async def scenario() -> tuple[str, list[str]]:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            await _active(app)
            name = app[mc._APP_SAMPLER_TASK].get_name()
            await _measure_one_run(app, peaks)
        return name, [task.get_name() for task in asyncio.all_tasks() if task.get_name() == SAMPLER_TASK]

    name, left_when_the_server_closed = asyncio.run(scenario())

    assert name == SAMPLER_TASK  # a stop's own kind of task, so a stop knows it
    assert left_when_the_server_closed == []
    assert _saved(own_data_dir)["observed_peaks_mb"] == peaks != []


def test_off_stops_the_watching_and_keeps_the_limit_and_what_it_learned(
    tmp_path: Path, own_data_dir: Path, peaks: list[float]
) -> None:
    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            runtime = await _active(app)
            await _measure_one_run(app, peaks)
            before = _saved(own_data_dir)
            limit = mc.max_concurrent_runs()

            await runtime.turn_off(ROW)
            assert state_of(runtime, ROW) == "off"
            assert KEYS.isdisjoint(app)

            _runs(app, A_RUN)
            await asyncio.sleep(0.2)  # twenty ticks of a sampler that should not be there
            _runs(app, {})
            await asyncio.sleep(0.2)

            assert len(peaks) == 1
            assert _saved(own_data_dir) == before
            assert mc.max_concurrent_runs() == limit
            refusal = mc.admission_refusal(limit)
            assert refusal is not None and refusal.startswith(
                f"All {limit} runs this computer can hold at once are busy"
            )

    asyncio.run(scenario())


def test_a_run_going_through_off_and_on_is_saved_with_only_what_was_seen_after_on(
    tmp_path: Path, own_data_dir: Path, peaks: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """What a row writes to its view leaves with it, so the peak so far goes, and the figure saved can be too low."""
    reading = {"a-run": 500.0}
    monkeypatch.setattr(mc, "sample_active_runs", lambda pids: {run: mb for run, mb in reading.items() if run in pids})

    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            runtime = await _active(app)
            _runs(app, A_RUN)
            await until(lambda: app[mc._APP_SAMPLER_PEAKS].get("a-run") == 500.0)

            await runtime.turn_off(ROW)
            reading["a-run"] = 100.0
            await runtime.turn_on(ROW)
            await _active(app)
            await until(lambda: app[mc._APP_SAMPLER_PEAKS].get("a-run") == 100.0)
            _runs(app, {})
            await until(lambda: peaks != [])

    asyncio.run(scenario())

    assert peaks == [100.0]


@pytest.mark.parametrize(("started_on", "saved_by_the_start"), [(True, True), (False, False)])
def test_with_the_row_off_thomas_measures_this_computer_the_first_time_it_needs_the_number(
    started_on: bool, saved_by_the_start: bool, tmp_path: Path, own_data_dir: Path
) -> None:
    """Nothing else asks at a start, so a new install with the row off has no saved limit until a run wants one."""
    choose(own_data_dir, on={ROW} if started_on else ())

    async def scenario() -> bool:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            await until(lambda: state_of(app[APP_RUNTIME_PLUGINS], ROW) != "loading")
            return (own_data_dir / "machine_capacity.json").is_file()

    assert asyncio.run(scenario()) is saved_by_the_start

    assert mc.max_concurrent_runs() >= 1
    assert _saved(own_data_dir)["source"] in ("measured", "cpu_only")


def test_the_record_of_where_the_time_went_goes_on_through_off(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = await _active(app)
            await runtime.turn_off(ROW)
            step_log.record("check", seconds=7.0, outcome="passed")
            await runtime.turn_on(ROW)
            await _active(app)
            answer = await client.get("/api/metrics/steps")
            assert answer.status == 200
            return await answer.json()

    assert asyncio.run(scenario())["by_step"]["check"]["count"] == 1


def test_nothing_but_the_sampler_teaches_the_limit() -> None:
    """Why off stops the learning. Check shards keep peaks of their own, and those never size a Build run."""
    teaching = re.compile(r"\brecord_run_peak\b")
    found = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "thomas").rglob("*.py")
        if teaching.search(path.read_text("utf-8"))
    }
    assert found == {"thomas/core/machine_capacity.py", "thomas/server/rows/machine_capacity.py"}  # its docstring


@pytest.fixture
def held() -> Iterator[threading.Event]:
    """Lets blocked work go, whatever a test did, or closing the server would wait for its thread."""
    gate = threading.Event()
    yield gate
    gate.set()


def test_a_stop_does_not_wait_for_the_sampler(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch, held: threading.Event
) -> None:
    """A slow walk of a run's processes is on a thread, so it can hold nothing up. ``stop_now`` counts only requests."""
    walking = threading.Event()

    def stuck(_pids: dict[str, int]) -> dict[str, float]:
        walking.set()
        held.wait(60)
        return {}

    monkeypatch.setattr(mc, "sample_active_runs", stuck)

    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            runtime = await _active(app)
            _runs(app, A_RUN)
            await until(walking.is_set)
            assert (await runtime.turn_off(ROW))["state"] == "off"
            held.set()

    asyncio.run(scenario())


def test_stop_now_fails_a_request_still_reading_the_figures(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch, held: threading.Event
) -> None:
    """What the row's ``stop_now`` says. The thread goes on to its end, and it only reads."""
    reading = threading.Event()

    def stuck(_rows: list[dict[str, Any]]) -> dict[str, Any]:
        reading.set()
        held.wait(60)
        return {}

    monkeypatch.setattr(step_report, "summarize", stuck)

    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = await _active(app)
            asked = asyncio.ensure_future(client.get("/api/metrics/steps"))
            await until(reading.is_set)
            stopping = asyncio.ensure_future(runtime.turn_off(ROW))
            await until(lambda: state_of(runtime, ROW) == "unloading")
            assert next(row for row in runtime.report()["rows"] if row["id"] == ROW)["waiting_for"] == 1
            await runtime.turn_off(ROW, force=True)
            with pytest.raises(aiohttp.ClientError):
                await asked
            assert (await stopping)["state"] == "off"
            held.set()

    asyncio.run(scenario())
