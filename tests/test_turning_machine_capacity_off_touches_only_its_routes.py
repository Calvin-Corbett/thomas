"""The machine_capacity row, off: its two routes answer 404, the memory sampler stops, and Build keeps its limit.

The registrar is a function in ``thomas/core/machine_capacity.py``, and that file cannot be this row's promise. Build reads
its limit there and the checks size themselves from it, so it stays loaded with the row off. ``thomas/core/step_report.py``
is the one module only these routes load, so that is what ``imports`` names and what off can hold to.

The sampler is an asyncio task, not a thread, so the name of a thread cannot show it. It starts from a startup hook, so a
route answering 404 says nothing of it either: the row can read off with every route gone and the sampler still writing
peaks. So each press here reads the running tasks, and ``tests/test_the_memory_sampler_through_off_and_on.py`` keeps what
happens to a run, to the saved limit, and to a stop.

The words ``machine`` and ``capacity`` name other things. ``thomas/core/machine_load.py`` keeps this PC under its load
limit, and its ``machine-load`` thread starts on first use and belongs to whoever asked first, so off leaves it alone.
``thomas/server/capacity_ledger.py`` holds what the checks have reserved. ``capacity`` on the Build queue's card is a third
thing, from a route of its own.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.plugin_view_fixture import state_of, until
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, choose
from thomas.core import machine_capacity as mc
from thomas.server import app_core
from thomas.server.live_routes import WebService
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, RuntimePlugins

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/machine/capacity": "GET /api/machine/capacity",
    "GET /api/metrics/steps": "GET /api/metrics/steps",
}
OWN_CODE = ("thomas.server.rows.machine_capacity", "thomas.core.step_report")
LISTED = {*ROUTES, "HEAD /api/machine/capacity", "HEAD /api/metrics/steps"}
KEPT_BY_BUILD = "thomas.core.machine_capacity"

ROW = "machine_capacity"
WEB_FOLDERS = ("thomas/server/web", "web", "desktop", "apps", "extensions")
SAMPLER = "_sampler_loop"

# A thread's name cannot show this: the sampler is a task on the server's own loop.
SAMPLER_TASKS = f"""\
def reading():
    named = [task.get_coro().__qualname__ for task in asyncio.all_tasks()]
    return [name for name in named if name == {SAMPLER!r}]


"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("machine-capacity-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder, reading=SAMPLER_TASKS)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("machine-capacity-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_own_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_the_file_build_reads_its_limit_from_is_still_there(seen: dict[str, Any]) -> None:
    """Why ``imports`` does not name it: off cannot promise this file, and the words must not."""
    assert KEPT_BY_BUILD in seen["loaded"]


def test_turning_it_on_brings_back_both_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == dict.fromkeys(ROUTES.values(), 200)


def test_the_sampler_runs_only_while_the_row_is_on(seen: dict[str, Any]) -> None:
    assert seen["read_off"] == []
    assert seen["read_on"] == [SAMPLER]
    assert seen["read_off_again"] == []


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert remote["with_token"] == dict.fromkeys(ROUTES.values(), 200)


def test_no_page_asks_for_these_routes() -> None:
    """The row's words say nothing you normally use changes. If a page starts calling these, they have to change."""
    wanted = ("api/machine/capacity", "api/metrics/steps", "machine/capacity", "metrics/steps")
    kinds = {".js", ".mjs", ".ts", ".tsx", ".html", ".vue"}
    files = [path for folder in WEB_FOLDERS for path in (ROOT / folder).rglob("*") if path.suffix in kinds]
    readable = [path for path in files if "node_modules" not in path.parts and path.is_file()]

    assert len(readable) > 100  # an empty search would pass
    assert [path for path in readable if any(word in path.read_text("utf-8", "replace") for word in wanted)] == []


@pytest.fixture
def only_this_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    choose(tmp_path / "data", on={ROW})


def _samplers() -> list[str]:
    return [task.get_name() for task in asyncio.all_tasks() if task.get_coro().__qualname__ == SAMPLER]


def test_the_routes_wait_for_the_first_measure_and_off_during_it_starts_no_sampler(
    tmp_path: Path, only_this_row: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row's routes join when its startup hooks end. That measure is on a thread, which a stop goes on without."""
    measuring, finish = threading.Event(), threading.Event()
    measure = mc.profile

    def slow() -> dict[str, Any]:
        measuring.set()
        finish.wait(60)
        return measure()

    monkeypatch.setattr(mc, "profile", slow)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        try:
            async with TestClient(TestServer(app)) as client:
                runtime = app[APP_RUNTIME_PLUGINS]
                await until(measuring.is_set)
                assert state_of(runtime, ROW) == "loading"
                assert (await client.get("/api/machine/capacity")).status == 404
                assert (await runtime.turn_off(ROW))["state"] == "off"
                finish.set()
                await asyncio.sleep(0.2)
                assert _samplers() == []
                assert mc._APP_SAMPLER_TASK not in app
        finally:
            finish.set()

    asyncio.run(scenario())


def test_a_first_measure_that_fails_reads_failed_and_on_tries_again(
    tmp_path: Path, only_this_row: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    measure = mc.profile

    def broken() -> dict[str, Any]:
        raise RuntimeError("no reading")

    monkeypatch.setattr(mc, "profile", broken)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            await until(lambda: state_of(runtime, ROW) != "loading")
            row = next(row for row in runtime.report()["rows"] if row["id"] == ROW)
            assert (row["state"], row["error"]) == ("failed", "RuntimeError: no reading")
            assert (await client.get("/api/machine/capacity")).status == 404
            assert _samplers() == []

            monkeypatch.setattr(mc, "profile", measure)
            await runtime.turn_on(ROW)
            await until(lambda: state_of(runtime, ROW) != "loading")
            assert state_of(runtime, ROW) == "active"
            assert (await client.get("/api/machine/capacity")).status == 200
            assert len(_samplers()) == 1

    asyncio.run(scenario())


def test_a_row_handed_no_guard_reads_failed_rather_than_answering_everyone(tmp_path: Path) -> None:
    """A real start always hands one over, so the server here is built without: nothing else reaches this line."""
    service = WebService(web.Application(), None, require_api_access=None, read_json=None)
    profile = views.profile_at(tmp_path / "profile.toml", [(ROW, f"thomas.server.rows.{ROW}:plugin", True)])
    runtime = RuntimePlugins(service, profile_path=profile, choices_path=tmp_path / "choices.json")

    runtime.load()

    row = next(row for row in runtime.report()["rows"] if row["id"] == ROW)
    assert (row["state"], row["error"]) == ("failed", f"RuntimeError: {ROW} has no access guard to register with")
    assert list(service.app.router._live.routes()) == []


@pytest.mark.parametrize("changed", ["thomas/server/rows/machine_capacity.py", "thomas/core/machine_capacity.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these three only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_machine_capacity_off_touches_only_its_routes.py" in chosen
    assert "tests/test_the_memory_sampler_through_off_and_on.py" in chosen
    assert "tests/test_run_limit_is_the_machines.py" in chosen
