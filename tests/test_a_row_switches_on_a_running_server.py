"""The switch on a running server: a bad table fails alone, the route list stays true, and nothing is left behind."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.plugin_view_fixture import (
    HERE,
    WRITTEN,
    events,
    hosted,
    mount_on,
    records,
    runtime_with,
    state_of,
    until,
)
from thomas.server import app_core, runtime_plugins
from thomas.server.app_keys import APP_MUTATING_ROUTE_POLICY_SNAPSHOT
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS


@pytest.fixture(autouse=True)
def _nothing_left_from_the_last_test() -> None:
    fixture.reset()


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


# -- a bad table --------------------------------------------------------------


def test_two_rows_claiming_one_route_leave_the_first_working_and_the_switch_usable(tmp_path: Path) -> None:
    async def scenario() -> None:
        rows = [("first", f"{HERE}:claims_a_route", True), ("second", f"{HERE}:claims_it_too", True)]
        runtime = runtime_with(tmp_path, rows)

        runtime.load()

        assert state_of(runtime, "first") == "active"
        assert state_of(runtime, "second") == "failed"
        assert "RuntimeError" in runtime.report()["rows"][1]["error"]
        async with TestClient(TestServer(runtime.web.app)) as client:
            assert (await client.get("/claimed")).status == 200

            await runtime.turn_off("first")  # the table the failed row left behind must not poison this
            assert (await client.get("/claimed")).status == 404

            await runtime.turn_on("second")
            assert state_of(runtime, "second") == "active"
            assert (await client.get("/claimed")).status == 200

    asyncio.run(scenario())


def test_two_rows_claiming_one_route_are_caught_with_another_route_after_the_claim(tmp_path: Path) -> None:
    """aiohttp compares a new path only with the last one added, so here it would see nothing wrong."""

    async def scenario() -> None:
        rows = [("first", f"{HERE}:claims_it_and_another", True), ("second", f"{HERE}:claims_it_too", True)]
        runtime = runtime_with(tmp_path, rows)

        runtime.load()

        assert state_of(runtime, "first") == "active"
        assert state_of(runtime, "second") == "failed"
        assert "/claimed" in runtime.report()["rows"][1]["error"]
        async with TestClient(TestServer(runtime.web.app)) as client:
            await runtime.turn_off("first")
            assert (await client.get("/claimed")).status == 404  # the refused row is not sitting in the shadow

    asyncio.run(scenario())


def _adds(*routes: tuple[str, str]) -> Any:
    def build(view: Any) -> None:
        for method, path in routes:
            view.router.add_route(method, path, fixture.ok)

    return build


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param([("GET", "/claimed"), ("GET", "/after")], [("GET", "/claimed")], id="a-route-between"),
        pytest.param([("GET", "/things/{id}")], [("GET", "/things/{name}")], id="the-same-path-by-another-name"),
        pytest.param([("*", "/claimed"), ("GET", "/after")], [("POST", "/claimed")], id="every-method-came-first"),
        pytest.param([("POST", "/claimed"), ("GET", "/after")], [("*", "/claimed")], id="every-method-came-second"),
    ],
)
def test_a_route_two_rows_claim_is_refused_however_it_is_written(first: Any, second: Any) -> None:
    _, kernel = hosted()
    mount_on(kernel, _adds(*first))

    with pytest.raises(RuntimeError, match="already holds"):
        mount_on(kernel, _adds(*second))


def test_two_rows_serving_one_folder_are_refused(tmp_path: Path) -> None:
    _, kernel = hosted()
    mount_on(
        kernel, lambda view: (view.router.add_static("/files", tmp_path), view.router.add_get("/after", fixture.ok))
    )

    with pytest.raises(RuntimeError, match="already holds"):
        mount_on(kernel, lambda view: view.router.add_static("/files", tmp_path))


def test_two_rows_may_share_a_path_on_different_methods() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        mount_on(kernel, _adds(("GET", "/shared"), ("GET", "/after")))
        mount_on(kernel, _adds(("POST", "/shared")))

        async with TestClient(TestServer(app)) as client:
            assert (await client.get("/shared")).status == 200
            assert (await client.post("/shared")).status == 200

    asyncio.run(scenario())


def test_a_row_that_repeats_its_own_route_is_left_as_a_real_app_would_leave_it() -> None:
    repeats = _adds(("GET", "/repeated"), ("GET", "/between"), ("GET", "/repeated"))
    repeats(web.Application())
    _, kernel = hosted()

    mount_on(kernel, repeats)  # a real app takes this, so a row must be able to as well


def test_a_bad_route_table_cannot_stop_a_real_server_starting(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            rows = {row["id"]: row for row in app[APP_RUNTIME_PLUGINS].report()["rows"]}
            assert rows["first"]["state"] == "active"
            assert rows["second"]["state"] == "failed"
            assert (await client.get("/claimed")).status == 200

    rows = [("first", f"{HERE}:claims_a_route", True), ("second", f"{HERE}:claims_it_too", True)]
    monkeypatch.setattr(runtime_plugins, "PROFILE_PATH", fixture.profile_at(tmp_path / "profile.toml", rows))
    asyncio.run(scenario())


def test_a_row_refused_on_a_running_server_leaves_no_work_running(tmp_path: Path) -> None:
    """It never got its fork, so no switch could reach the work if the failure left it going."""

    async def scenario() -> None:
        rows = [("first", f"{HERE}:claims_a_route", True), ("second", f"{HERE}:works_then_claims_a_route", False)]
        runtime = runtime_with(tmp_path, rows)
        runtime.load()
        runtime.mark_ready()

        report = await runtime.turn_on("second")

        assert report["state"] == "failed"
        assert "RuntimeError" in report["error"]
        assert not any(task.get_name().endswith(":work") for task in asyncio.all_tasks())

    asyncio.run(scenario())


def test_a_row_that_raises_in_apply_leaves_no_work_running_however_often_it_is_pressed(tmp_path: Path) -> None:
    """``apply`` raising takes its scope with it, so ``stop`` finds nothing and the disposing has to end the work."""

    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("row", f"{HERE}:works_then_raises", False)])
        runtime.load()
        runtime.mark_ready()

        for _ in range(3):
            report = await runtime.turn_on("row")
            assert report["state"] == "failed"
            assert "OSError" in report["error"]

        await runtime.turn_off("row")
        assert not any(task.get_name().endswith(":work") for task in asyncio.all_tasks())

    asyncio.run(scenario())


def _refused_row_setup(tmp_path: Path, bad: str, *, older: bool) -> Any:
    """A row using the service, a row holding ``/claimed``, and ``bad``, off, offering the service and claiming that."""
    rows = [
        ("dep", f"{HERE}:needs_a_thing_and_is_busy", True),
        ("claimer", f"{HERE}:claims_a_route", True),
        ("bad", f"{HERE}:{bad}", False),
    ]
    runtime = runtime_with(tmp_path, rows)
    if older:
        runtime.kernel.root.set("thing", "the older value")
    runtime.load()
    runtime.mark_ready()
    return runtime


def test_a_refused_row_leaves_a_row_already_using_its_service_untouched(tmp_path: Path) -> None:
    """A failed press of one switch must not cost a healthy row its running request, its routes or its scope."""

    async def scenario() -> None:
        runtime = _refused_row_setup(tmp_path, "provides_a_thing_then_claims_a_route", older=True)
        async with TestClient(TestServer(runtime.web.app)) as client:
            assert (await client.get("/needs")).status == 200
            slow = asyncio.create_task(client.get("/slow"))
            await until(lambda: "slow began" in events)

            report = await runtime.turn_on("bad")

            assert report["state"] == "failed"
            assert state_of(runtime, "dep") == "active"
            assert (await client.get("/needs")).status == 200
            assert not slow.done()
            assert fixture.applied.count("needs-a-thing-and-is-busy") == 1  # it never had to start again
            assert "cleaned up" not in events

            fixture.release_slow.set()
            assert await (await slow).text() == "finished"

    asyncio.run(scenario())


def test_a_row_a_refused_row_brought_up_goes_with_it_properly(tmp_path: Path) -> None:
    """It only came up on the refused row's service, so it leaves with it, and through ``stop`` so its cleanups run."""

    async def scenario() -> None:
        runtime = _refused_row_setup(tmp_path, "provides_a_thing_then_claims_a_route", older=False)
        assert state_of(runtime, "dep") == "pending"
        async with TestClient(TestServer(runtime.web.app)) as client:
            report = await runtime.turn_on("bad")

            assert report["state"] == "failed"
            assert state_of(runtime, "dep") == "pending"
            assert events == ["cleaned up"]
            assert (await client.get("/needs")).status == 404
            assert (await client.get("/claimed")).status == 200

    asyncio.run(scenario())


def test_a_row_that_outlives_a_refused_row_keeps_its_routes(tmp_path: Path) -> None:
    """The service stays when the refused row goes, so its dependant comes back, and must not read active behind a 404."""

    async def scenario() -> None:
        runtime = _refused_row_setup(tmp_path, "leaves_a_thing_behind_then_claims_a_route", older=False)
        async with TestClient(TestServer(runtime.web.app)) as client:
            report = await runtime.turn_on("bad")

            assert report["state"] == "failed"
            assert state_of(runtime, "dep") == "active"
            assert (await client.get("/needs")).status == 200

    asyncio.run(scenario())


def test_a_dependant_that_outlives_its_provider_keeps_its_routes(tmp_path: Path) -> None:
    """An older value of the service comes back, so the dependant restarts, and must not read active behind a 404."""

    async def scenario() -> None:
        rows = [("provider", f"{HERE}:provides_a_thing", True), ("dependant", f"{HERE}:needs_a_thing", True)]
        runtime = runtime_with(tmp_path, rows)
        runtime.kernel.root.set("thing", "the older value")
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            assert (await client.get("/needs")).status == 200

            await runtime.turn_off("provider")

            assert state_of(runtime, "dependant") == "active"
            assert (await client.get("/needs")).status == 200

    asyncio.run(scenario())


def test_the_hooks_of_a_plugin_that_failed_to_mount_never_run() -> None:
    async def scenario() -> None:
        _, kernel = hosted()
        kernel.mark_ready()

        def apply(ctx: Any, config: Any) -> None:
            ctx["web"].view(ctx).on_startup.append(records("started"))
            raise OSError("apply fell over after adding a hook")

        with pytest.raises(OSError):
            kernel.mount(SimpleNamespace(name="row", inject=("web",), apply=apply))
        await until(lambda: not any(task.get_name().endswith("startup hooks") for task in asyncio.all_tasks()))

        assert events == []

    asyncio.run(scenario())


# -- the route snapshot, and what the wave promised ---------------------------


@pytest.mark.filterwarnings("error:Changing state of started:DeprecationWarning")
def test_the_route_snapshot_follows_the_switch(tmp_path: Path, own_data_dir: Path) -> None:
    def companion_paths(app: web.Application) -> set[str]:
        policies = app[APP_MUTATING_ROUTE_POLICY_SNAPSHOT]["policies"]
        return {row["path"] for row in policies if row["path"].startswith("/api/companion/")}

    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            runtime = app[APP_RUNTIME_PLUGINS]
            before = companion_paths(app)
            assert before  # an empty compare would pass

            await runtime.turn_off("companion")
            assert companion_paths(app) == set()

            await runtime.turn_on("companion")
            assert companion_paths(app) == before

    asyncio.run(scenario())


def test_a_row_goes_off_and_on_a_hundred_times_and_nothing_grows(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("all", f"{HERE}:everything", True)])
        runtime.load()
        runtime.mark_ready()
        app = runtime.web.app

        def counts() -> tuple[int, ...]:
            others = {task for task in asyncio.all_tasks() if "startup hooks" not in task.get_name()}
            root = runtime.kernel.root
            return root.pending_effects, len(runtime.kernel.mounted()), len(app), len(runtime.web._rows), len(others)

        async with TestClient(TestServer(app)) as client:
            await until(lambda: "started" in events)
            before = counts()

            for _ in range(100):
                await runtime.turn_off("all")
                assert WRITTEN not in app
                await runtime.turn_on("all")

            await until(lambda: events.count("started") == 101)
            assert events.count("cleaned up") == 100
            assert counts() == before
            assert await (await client.get("/written")).text() == "from the plugin"

    asyncio.run(scenario())


def test_the_server_starts_with_every_row_off(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            rows = app[APP_RUNTIME_PLUGINS].report()["rows"]
            assert rows  # an empty compare would pass
            assert {row["state"] for row in rows if not row["required"]} == {"off"}
            assert {row["state"] for row in rows if row["required"]} == {"active"}  # no off switch
            assert (await client.get("/api/companion/v1/status")).status == 404

    choices = own_data_dir / "plugins" / "choices.json"
    choices.parent.mkdir(parents=True)
    rows = runtime_plugins.read_profile(runtime_plugins.PROFILE_PATH).entries
    choices.write_text(json.dumps({row.id: {"enabled": False} for row in rows}), encoding="utf-8")
    asyncio.run(scenario())


def test_hooks_run_when_a_real_server_starts_and_stops(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            await until(lambda: events == ["started"])
        assert events == ["started", "cleaned up"]

    profile = fixture.profile_at(tmp_path / "profile.toml", [("hooks", f"{HERE}:adds_hooks", True)])
    monkeypatch.setattr(runtime_plugins, "PROFILE_PATH", profile)
    asyncio.run(scenario())
