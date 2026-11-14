"""The proof of every row has to be able to say no, so each of its refusals is shown here, on rows made to fail it.

tests/test_every_row_keeps_its_promises.py runs the proof on the real rows.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests import row_proof_fixture as row_proof
from tests import test_a_row_cannot_shadow_the_server as server_proof
from tests import test_every_row_keeps_its_promises as every_row_proof
from tests.plugin_view_fixture import until
from tests.row_proof_fixture import (
    complaints,
    kept_modules_in,
    kept_routes_a_row_answers,
    leaves_nothing_behind,
    reaches_the_shell,
)
from thomas.core import plugin_fence
from thomas.core.kernel import Entry
from thomas.server import app_core, runtime_plugins
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

HERE = __name__
log = logging.getLogger(__name__)

gate: asyncio.Event | None = None  # what the throwaway row's slow request waits for
already_registered = False  # the note the row that registers once keeps


class _Throwaway:
    """All a later row will need from the floor under it, in one row."""

    name = "throwaway"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        view = ctx["web"].view(ctx)
        view[fixture.WRITTEN] = "written on a frozen app"
        view.on_cleanup.append(fixture.records("cleaned up"))
        view.router.add_get("/throwaway/written", fixture.read_written)
        view.router.add_get("/throwaway/slow", fixture.waits_for(gate))


class _LeavesAnEffectBehind:
    name = "leaves-an-effect-behind"
    inject = ()

    def apply(self, ctx: Any, config: Any) -> None:
        ctx.kernel.root.effect(lambda: None)


class _Claims:
    inject = ("web",)

    def __init__(self, path: str) -> None:
        self.name = f"claims {path}"
        self._path = path

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx).router.add_get(self._path, fixture.ok)


class _StartsSlowly:
    inject = ("web",)

    def __init__(self, name: str, hook: Callable[[Any], Awaitable[None]]) -> None:
        self.name = name
        self._hook = hook

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx).on_startup.append(self._hook)


# What a slow start is, not a wait: no test here learns anything from how long it takes. It only has to outlast the save
# in a press, so that an off pressed straight after an on reaches the hook before it is done.
A_SLOW_START = 0.05
held_open = threading.Event()  # what the threads of the row that leaves them running wait for


async def _fails_after_a_timer(_app: Any) -> None:
    await asyncio.sleep(A_SLOW_START)
    raise OSError("this row can never start")


async def _fails_after_a_thread(_app: Any) -> None:
    await asyncio.to_thread(time.sleep, A_SLOW_START)
    raise OSError("this row can never start")


async def _starts_a_thread(_app: Any) -> None:
    await asyncio.sleep(A_SLOW_START)
    threading.Thread(target=held_open.wait, daemon=True).start()


class _LeavesARouteBehind:
    """Its route is on the root scope, so stopping this row takes nothing with it."""

    name = "leaves-a-route-behind"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx.kernel.root).router.add_get("/left-behind", fixture.ok)


class _RegistersOnce:
    """A registrar that keeps a module-level note that it has run, so a second apply adds nothing and reads active."""

    name = "registers-once"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        global already_registered
        if not already_registered:
            ctx["web"].view(ctx).router.add_get("/once", fixture.ok)
            already_registered = True


class _GivesUp:
    """What ``register_companion_route_family`` does with a failure: catch it, log it under its own name, read active."""

    name = "gives-up"
    inject = ("web",)

    def __init__(self, *, from_apply: int) -> None:
        self._from_apply = from_apply
        self.applied = 0

    def apply(self, ctx: Any, config: Any) -> None:
        self.applied += 1
        try:
            if self.applied >= self._from_apply:
                raise RuntimeError("this family cannot register")
            ctx["web"].view(ctx).router.add_get("/gives-up", fixture.ok)
        except RuntimeError as exc:
            log.warning("Routes unavailable: %s", exc)


throwaway = _Throwaway()
leaves_a_route_behind = _LeavesARouteBehind()
registers_once = _RegistersOnce()
gives_up_the_second_time = _GivesUp(from_apply=2)
gives_up_every_time = _GivesUp(from_apply=1)
leaves_an_effect_behind = _LeavesAnEffectBehind()
fails_after_a_timer = _StartsSlowly("fails-after-a-timer", _fails_after_a_timer)
fails_after_a_thread = _StartsSlowly("fails-after-a-thread", _fails_after_a_thread)
leaves_a_thread_running = _StartsSlowly("leaves-a-thread-running", _starts_a_thread)
claims_preferences = _Claims("/api/preferences")
claims_everything_under_api = _Claims("/api/{anything}")


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _proof_refuses(tmp_path: Path, attribute: str, complaint: str) -> None:
    async def scenario() -> None:
        runtime = fixture.runtime_with(tmp_path, [("row", f"{HERE}:{attribute}", True)])
        runtime.load()
        runtime.mark_ready()
        with pytest.raises(AssertionError, match=complaint):
            await leaves_nothing_behind(runtime, "row")

    asyncio.run(scenario())


def test_this_proof_catches_a_row_that_leaves_something_behind(tmp_path: Path) -> None:
    _proof_refuses(tmp_path, "leaves_an_effect_behind", "effects on the root")


@pytest.mark.parametrize("attribute", ["fails_after_a_timer", "fails_after_a_thread"])
def test_this_proof_catches_a_row_that_can_never_finish_starting(attribute: str, tmp_path: Path) -> None:
    _proof_refuses(tmp_path, attribute, "this row can never start")


def test_this_proof_catches_a_row_that_is_off_and_still_answers(tmp_path: Path) -> None:
    _proof_refuses(tmp_path, "leaves_a_route_behind", "still answers")


def test_this_proof_catches_a_row_that_comes_back_on_without_its_routes(tmp_path: Path) -> None:
    global already_registered
    already_registered = False
    _proof_refuses(tmp_path, "registers_once", "came back on with")


def test_this_proof_catches_a_row_that_swallows_a_failure_on_its_second_apply(tmp_path: Path) -> None:
    gives_up_the_second_time.applied = 0
    _proof_refuses(tmp_path, "gives_up_the_second_time", "came back on with")


def test_this_proof_hears_a_registrar_that_gives_up_every_time(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Its routes were never there to come back, so the table has nothing to say, and the row reads active throughout."""
    gives_up_every_time.applied = 0
    runtime = fixture.runtime_with(tmp_path, [("row", f"{HERE}:gives_up_every_time", True)])

    with caplog.at_level(logging.WARNING):
        runtime.load()

    assert fixture.state_of(runtime, "row") == "active"
    assert complaints(caplog, Entry(id="row", plugin=f"{HERE}:gives_up_every_time")) == [
        "Routes unavailable: this family cannot register"
    ]


def test_this_proof_catches_a_row_that_leaves_a_thread_running_each_time_it_starts(tmp_path: Path) -> None:
    held_open.clear()
    try:
        _proof_refuses(tmp_path, "leaves_a_thread_running", "active_count")
    finally:
        held_open.set()


def test_a_throwaway_row_does_all_a_later_row_will_need(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A new app key on a frozen app, a cleanup held until a running request ends, and 100 presses on a real server."""

    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            assert app.frozen and fixture.WRITTEN not in app

            await runtime.turn_on("row")
            assert await (await client.get("/throwaway/written")).text() == "written on a frozen app"

            slow = asyncio.ensure_future(client.get("/throwaway/slow"))
            await until(lambda: runtime._row("row").fork.ctx.working == 1)
            turning_off = asyncio.ensure_future(runtime.turn_off("row"))
            await until(lambda: list(app.router._live.routes()) == [])
            assert (await client.get("/throwaway/written")).status == 404
            assert fixture.state_of(runtime, "row") == "unloading" and fixture.events == []

            gate.set()
            assert (await slow).status == 200
            await turning_off
            assert fixture.events == ["request finished", "cleaned up"]
            assert fixture.WRITTEN not in app

            await runtime.turn_on("row")
            await leaves_nothing_behind(runtime, "row")

    fixture.reset()
    profile = fixture.profile_at(tmp_path / "profile.toml", [("row", f"{HERE}:throwaway", False)])
    monkeypatch.setattr(runtime_plugins, "PROFILE_PATH", profile)
    with caplog.at_level(logging.WARNING):
        asyncio.run(scenario())
    assert complaints(caplog, Entry(id="row", plugin=f"{HERE}:throwaway")) == []


@pytest.mark.parametrize(
    "source",
    [
        "def apply(ctx, config):\n    from thomas.server.routes.preferences_aiohttp import register_preferences_routes\n",
        "from thomas.server.routes import preferences_aiohttp\n",
    ],
    ids=["inside apply", "at the top of the file"],
)
def test_the_keep_in_shell_list_refuses_a_row_that_imports_it(source: str) -> None:
    imported = [module for _, module in plugin_fence.imports("row.py", source)]

    assert kept_modules_in(imported) == {"thomas.server.routes.preferences_aiohttp"}


@pytest.mark.parametrize(
    "module", ["tests.row_names_the_shell_fixture", "tests.row_imports_the_shell_fixture"], ids=["names", "imports"]
)
def test_the_proof_refuses_a_row_that_reaches_the_shell(module: str) -> None:
    assert reaches_the_shell(Entry(id="row", plugin=f"{module}:plugin")) == {"thomas.server.routes.preferences_aiohttp"}


def test_a_row_that_keeps_clear_of_the_shell_is_not_refused() -> None:
    """The refusal above would pass for a function that refused everything."""
    assert reaches_the_shell(Entry(id="row", plugin="tests.runtime_plugin_fixture:quiet")) == set()


@pytest.mark.parametrize("attribute", ["claims_preferences", "claims_everything_under_api"])
def test_the_keep_in_shell_list_refuses_a_row_that_answers_its_route(attribute: str, tmp_path: Path) -> None:
    runtime = fixture.runtime_with(tmp_path, [("row", f"{HERE}:{attribute}", True)])
    runtime.load()

    assert "GET /api/preferences" in asyncio.run(kept_routes_a_row_answers(runtime))


def _ship(row: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The real proof, on a profile holding this row alone, as if it had landed. Returns the data folder it uses."""
    entry = f"tests.row_with_a_startup_hook_fixture:{row}"
    profile = fixture.profile_at(tmp_path / "shipped.toml", [(row, entry, True)])
    rows = runtime_plugins.read_profile(profile).entries
    monkeypatch.setattr(runtime_plugins, "PROFILE_PATH", profile)
    monkeypatch.setattr(row_proof, "ROWS", rows)
    monkeypatch.setattr(every_row_proof, "ROWS", rows)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_a_row_with_a_startup_hook_needs_no_change_to_the_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It reads loading until a server has run its hooks, and rows are built in parallel on these shared files."""
    data = _ship("well_behaved", tmp_path, monkeypatch)

    every_row_proof.test_no_row_holds_what_stays_in_the_shell(tmp_path, data)
    server_proof.test_the_shipped_rows_load_and_stay_up_when_a_real_server_starts(tmp_path, monkeypatch)


def test_the_proof_refuses_a_row_that_takes_the_off_switch_while_it_waits_for_its_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its routes join when the hooks end, so being off the live table now is no defence. The server's own route is a
    pattern, which the route table's check does not reach, so this is the only thing that refuses it."""
    data = _ship("takes_the_off_switch", tmp_path, monkeypatch)

    with pytest.raises(AssertionError, match="/off"):  # pytest shortens and colours the rest of the route
        every_row_proof.test_no_row_holds_what_stays_in_the_shell(tmp_path, data)


def test_the_proof_refuses_a_row_that_did_not_come_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reading loading passes it, so reading failed must not: it would hold no routes, and pass for owning nothing."""
    data = _ship("fails_to_load", tmp_path, monkeypatch)

    with pytest.raises(AssertionError, match="failed"):
        every_row_proof.test_no_row_holds_what_stays_in_the_shell(tmp_path, data)


def test_the_proof_is_not_passed_by_a_list_that_loaded_no_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no rows there is nothing to refuse, and every check after this one reads an empty list."""
    data = _ship("well_behaved", tmp_path, monkeypatch)
    runtime_plugins.PROFILE_PATH.write_text("this is not a profile", encoding="utf-8")

    with pytest.raises(AssertionError):
        every_row_proof.test_no_row_holds_what_stays_in_the_shell(tmp_path, data)
