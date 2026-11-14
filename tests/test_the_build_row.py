"""The Build row has no off switch, serves its 41 routes from the live table, and ends what the loop started.

``thomas.server.rows.build`` registers the directed Code surface (``/api/evolve/agent/*``) and the loop dashboard
(``/api/evolve/loop/*`` and ``/api/evolve/orchestration/*``) that the server's shell used to register itself. It names
``thomas.server.routes.evolve_agent_routes`` and ``thomas.server.routes.evolve_loop_routes``, which a check follows to
this file. The words of the row are held sentence by sentence in ``tests/test_the_build_row_says_what_is_true.py``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from tests.build_row_fixture import AGENT, ROUTES, STREAMS, FakeProcess, build_row, named, running
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select
from thomas.server.routes import evolve_agent_routes, evolve_loop_routes
from thomas.server.routes.evolve_loop_routes import APP_EVOLVE_TASK, end_loop_processes


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Choices are saved under the data folder, so a test that presses a switch must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_the_row_is_required_and_on_with_all_its_routes_live(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        async with running(tmp_path) as (app, runtime, _client):
            row = build_row(runtime)
            assert (row["required"], row["enabled"], row["state"]) == (True, True, "active"), row
            assert set(ROUTES) <= named(app.router._live.routes())
            assert len(ROUTES) == 41

    asyncio.run(scenario())


def test_the_shell_no_longer_registers_any_of_them(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        async with running(tmp_path) as (app, _runtime, _client):
            shell = named(app.router.server_routes())
            assert {route for route in shell if "/api/evolve/" in route} == set()

    asyncio.run(scenario())


def test_the_two_streams_are_routes_the_row_names() -> None:
    from thomas.server.rows.build import STREAMS as named_streams

    assert named_streams == STREAMS
    assert {f"GET {path}" for path in STREAMS} <= set(AGENT)


def test_both_streams_are_named_to_the_view_and_found_in_the_routes(tmp_path: Path, own_data_dir: Path) -> None:
    """An open page on either holds the stop until it is ended, so they are named, and each one was registered."""

    async def scenario() -> None:
        async with running(tmp_path) as (_app, runtime, _client):
            ending = runtime.web._streams[runtime._row("build").fork.ctx]
            assert (ending.named, ending.registered) == (set(STREAMS), set(STREAMS))

    asyncio.run(scenario())


def test_the_row_names_its_own_code_and_loads_no_other_row() -> None:
    from thomas.server.rows.build import plugin

    assert plugin.name == "build"
    assert plugin.imports == (
        "thomas.server.routes.evolve_agent_routes",
        "thomas.server.routes.evolve_loop_routes",
    )


def test_turning_it_off_is_refused_with_or_without_force(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        async with running(tmp_path) as (app, runtime, client):
            for query in ("", "?force=1"):
                answer = await client.post(f"/api/plugins/thomas/build/off{query}")
                assert answer.status == 409
                assert "cannot be turned off" in await answer.text()
            assert build_row(runtime)["state"] == "active"
            assert set(ROUTES) <= named(app.router._live.routes())

    asyncio.run(scenario())


def test_a_saved_off_does_not_stop_the_row_loading(tmp_path: Path, own_data_dir: Path) -> None:
    choices = own_data_dir / "plugins" / "choices.json"
    choices.parent.mkdir(parents=True)
    choices.write_text('{"build": {"enabled": false}}', encoding="utf-8")

    async def scenario() -> None:
        async with running(tmp_path) as (app, runtime, _client):
            assert build_row(runtime)["state"] == "active"
            assert set(ROUTES) <= named(app.router._live.routes())

    asyncio.run(scenario())


def test_a_handler_writes_to_the_real_app_and_not_to_the_row_s_view(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop's start keeps its process on the app. A row that built its handlers on the view would lose it."""
    started: list[list[str]] = []
    process = FakeProcess()

    async def spawn(_root: Path, args: list[str]) -> FakeProcess:
        started.append(args)
        return process

    monkeypatch.setattr(evolve_loop_routes, "_spawn_evolve_cli", spawn)

    async def scenario() -> None:
        async with running(tmp_path) as (app, _runtime, client):
            answer = await client.post("/api/evolve/loop/start", json={"posture": "auto_safe"})
            assert answer.status == 200
            assert app[APP_EVOLVE_TASK] is process
            again = await client.post("/api/evolve/loop/start", json={})
            assert again.status == 409  # it sees the process it started

    asyncio.run(scenario())
    assert len(started) == 1
    assert process.terminated == 1  # still running when the server closed, and the stop found it on the real app


def test_a_registrar_that_fails_leaves_the_server_up_and_try_again_starts_the_row_once(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real = evolve_agent_routes.register_evolve_agent_routes
    failures = [RuntimeError("no registrar today")]

    def fails_once(*args: Any, **kwargs: Any) -> None:
        if failures:
            raise failures.pop()
        real(*args, **kwargs)

    monkeypatch.setattr(evolve_agent_routes, "register_evolve_agent_routes", fails_once)

    async def scenario() -> None:
        with caplog.at_level(logging.WARNING):
            async with running(tmp_path) as (app, runtime, client):
                row = build_row(runtime)
                assert (row["state"], row["required"]) == ("failed", True), row
                assert "no registrar today" in row["error"]
                assert (await client.get("/api/health")).status == 200  # the server carries on
                live = named(app.router._live.routes())
                assert [route for route in live if "/api/evolve/" in route] == []  # nothing half registered

                report = await runtime.turn_on("build")

                assert (report["state"], report["error"]) == ("active", "")
                routes = [f"{route.method} {route.resource.canonical}" for route in app.router._live.routes()]
                assert set(ROUTES) <= set(routes)
                assert [route for route in routes if route == "POST /api/evolve/agent/send"] == [
                    "POST /api/evolve/agent/send"
                ]
                assert (await client.get("/api/evolve/loop/status")).status == 200

    asyncio.run(scenario())
    assert any("Evolve loop routes unavailable: no registrar today" in line for line in caplog.messages)


def test_the_loop_and_every_approval_it_started_are_ended_and_nothing_else(tmp_path: Path) -> None:
    app = web.Application()
    loop, approval, over, other = FakeProcess(), FakeProcess(), FakeProcess(), FakeProcess()
    over.returncode = 0
    app[APP_EVOLVE_TASK] = loop
    app["evolve_approve_a1"] = approval
    app["evolve_approve_a0"] = over
    app["something_else"] = other

    asyncio.run(end_loop_processes(app))

    assert (loop.terminated, approval.terminated, over.terminated, other.terminated) == (1, 1, 0, 0)
    assert loop.returncode is not None and approval.returncode is not None


def test_a_process_that_ignores_terminate_is_killed(tmp_path: Path) -> None:
    app = web.Application()
    stubborn = FakeProcess(ends_when_told=False)
    app[APP_EVOLVE_TASK] = stubborn

    asyncio.run(end_loop_processes(app, grace=0.05))

    assert (stubborn.terminated, stubborn.killed) == (1, 1)


def test_a_server_that_closes_ends_the_process_the_loop_started(tmp_path: Path, own_data_dir: Path) -> None:
    process = FakeProcess()

    async def scenario() -> None:
        async with running(tmp_path, before_start=lambda app: app.__setitem__(APP_EVOLVE_TASK, process)):
            assert process.terminated == 0  # a running server does not end it

    asyncio.run(scenario())

    assert process.terminated == 1
    assert process.returncode is not None


def test_a_row_that_fails_to_start_ends_nothing(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No routes were ever live, so no process can have been started through them, and no stop step was made."""
    process = FakeProcess()

    def refuses(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("no")

    monkeypatch.setattr(evolve_agent_routes, "register_evolve_agent_routes", refuses)

    async def scenario() -> None:
        async with running(tmp_path, before_start=lambda app: app.__setitem__(APP_EVOLVE_TASK, process)):
            pass

    asyncio.run(scenario())
    assert process.terminated == 0


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/rows/build.py",
        "thomas/server/routes/evolve_agent_routes.py",
        "thomas/server/routes/evolve_loop_routes.py",
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    chosen = select(ROOT, [changed]).files
    assert "tests/test_the_build_row.py" in chosen
