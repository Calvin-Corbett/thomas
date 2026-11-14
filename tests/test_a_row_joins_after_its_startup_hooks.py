"""On a running server a row's routes join when its startup hooks end, because a real server finishes on_startup first.

Before that a handler reading a key its hook sets answered 500, while the row read active.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.plugin_view_fixture import WRITTEN, events, hosted, mount_on, ok, read_written, runtime_with, state_of, until

HERE = __name__
gate: asyncio.Event | None = None  # what a startup hook waits for
failures_left = 0  # how many starts fail before one works
inner: asyncio.Future[Any] | None = None  # what a startup hook leans on, which something else may cancel
first_gate: asyncio.Event | None = None  # what the first of two hooks waits for


async def _hook(app: Any) -> None:
    global failures_left
    events.append("hook began")
    await gate.wait()
    if failures_left:
        failures_left -= 1
        raise OSError("this row cannot start")
    app[WRITTEN] = "written by the hook"
    events.append("hook finished")


async def _around(app: Any) -> Any:
    await _hook(app)
    yield


async def _leans_on_inner_work(app: Any) -> None:
    """Ends cancelled the first time, because what it awaits was cancelled by something that is not a stop."""
    global inner
    if inner is None:
        inner = asyncio.ensure_future(asyncio.Event().wait())
        await inner
    app[WRITTEN] = "written by the hook"


class _StartsSlowly:
    """Its route reads a key its hook writes, which on a real server is always there."""

    def __init__(self, name: str, *needs: str, kind: str = "on_startup", hook: Any = _hook) -> None:
        self.name = name
        self.inject = ("web", *needs)
        self._kind = kind
        self._hook = hook

    def apply(self, ctx: Any, config: Any) -> None:
        view = ctx["web"].view(ctx)
        if self._kind == "on_startup":
            view.on_startup.append(self._hook)
        else:
            view.cleanup_ctx.append(_around)
        view.on_cleanup.append(fixture.records("cleaned up"))
        view.router.add_get("/reads", read_written)


class _TwoViews:
    """Each view of a row has hooks of its own, and its routes wait for both."""

    name = "two-views"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        first = ctx["web"].view(ctx)
        first.on_startup.append(fixture.records("first view started"))
        first.router.add_get("/ok", ok)
        second = ctx["web"].view(ctx)
        second.on_startup.append(_hook)


class _AddsAViewDuringItsHook:
    """A registrar run from a hook, so its view and its hook only arrive once the first hook is well under way."""

    name = "adds-a-view-during-its-hook"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        async def first(_app: Any) -> None:
            events.append("first hook began")
            await first_gate.wait()
            ctx["web"].view(ctx).on_startup.append(_hook)

        view = ctx["web"].view(ctx)
        view.on_startup.append(first)
        view.router.add_get("/reads", read_written)


class _ProvidesAThingAndStartsSlowly(_StartsSlowly):
    def apply(self, ctx: Any, config: Any) -> None:
        ctx.set("thing", "from a row still starting")
        super().apply(ctx, config)


adds_a_view_during_its_hook = _AddsAViewDuringItsHook()
provides_a_thing_and_starts_slowly = _ProvidesAThingAndStartsSlowly("provides-and-starts-slowly")
starts_slowly = _StartsSlowly("starts-slowly")
opens_slowly = _StartsSlowly("opens-slowly", kind="cleanup_ctx")
leans_on_inner_work = _StartsSlowly("leans-on-inner-work", hook=_leans_on_inner_work)
needs_a_thing_and_starts_slowly = _StartsSlowly("needs-a-thing", "thing")
two_views = _TwoViews()
provides_a_thing = fixture.provides_a_thing


@pytest.fixture(autouse=True)
def _nothing_left_from_the_last_test() -> None:
    global gate, failures_left, inner
    fixture.reset()
    gate = None
    failures_left = 0
    inner = None


def _running(tmp_path: Path, *rows: tuple[str, str, bool]) -> Any:
    runtime = runtime_with(tmp_path, list(rows))
    runtime.load()
    runtime.mark_ready()
    return runtime


def _live(runtime: Any) -> list[str]:
    return sorted({route.resource.canonical for route in runtime.web._router._live.routes()})


@pytest.mark.parametrize("row", ["starts_slowly", "opens_slowly"])
def test_a_row_reads_loading_and_stays_off_the_table_until_its_hooks_finish(row: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        runtime = _running(tmp_path, ("a", f"{HERE}:{row}", False))
        async with TestClient(TestServer(runtime.web.app)) as client:
            report = await runtime.turn_on("a")
            await until(lambda: "hook began" in events)

            assert report["state"] == "loading"
            assert state_of(runtime, "a") == "loading"
            assert _live(runtime) == []
            assert (await client.get("/reads")).status == 404

            gate.set()
            await until(lambda: state_of(runtime, "a") == "active")

            answer = await client.get("/reads")
            assert (answer.status, await answer.text()) == (200, "written by the hook")

    asyncio.run(scenario())


def test_off_pressed_while_a_hook_waits_ends_the_hook(tmp_path: Path) -> None:
    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        runtime = _running(tmp_path, ("a", f"{HERE}:starts_slowly", False))
        app = runtime.web.app
        async with TestClient(TestServer(app)) as client:
            await runtime.turn_on("a")
            await until(lambda: "hook began" in events)

            report = await asyncio.wait_for(runtime.turn_off("a"), timeout=30)

            assert report["state"] == "off"
            assert events == ["hook began", "cleaned up"]
            assert (await client.get("/reads")).status == 404
            assert runtime.web._rows == {} and runtime.web._held == {}

            gate.set()
            await runtime.turn_on("a")
            await until(lambda: state_of(runtime, "a") == "active")
            assert await (await client.get("/reads")).text() == "written by the hook"

    asyncio.run(scenario())


def test_a_row_whose_hook_fails_never_goes_live_and_holds_no_claim(tmp_path: Path) -> None:
    async def scenario() -> None:
        global gate, failures_left
        gate = asyncio.Event()
        failures_left = 1
        runtime = _running(tmp_path, ("a", f"{HERE}:starts_slowly", False))
        async with TestClient(TestServer(runtime.web.app)) as client:
            await runtime.turn_on("a")
            await until(lambda: "hook began" in events)

            gate.set()
            await until(lambda: state_of(runtime, "a") == "failed")

            assert "this row cannot start" in runtime.report()["rows"][0]["error"]
            assert _live(runtime) == []
            assert (await client.get("/reads")).status == 404
            assert runtime.web._rows == {} and runtime.web._scratch == {} and runtime.web._held == {}

            await runtime.turn_on("a")  # try again, which cleans up what the first try opened
            await until(lambda: state_of(runtime, "a") == "active")

            assert events.count("cleaned up") == 1
            assert await (await client.get("/reads")).text() == "written by the hook"

    asyncio.run(scenario())


def test_a_hook_cancelled_with_no_stop_anywhere_reads_failed_and_try_again_works(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing asked this row to stop, so ending quietly would leave it reading loading for ever, with no reason."""

    async def scenario() -> None:
        runtime = _running(tmp_path, ("a", f"{HERE}:leans_on_inner_work", False))
        async with TestClient(TestServer(runtime.web.app)) as client:
            await runtime.turn_on("a")
            await until(lambda: inner is not None)
            await asyncio.sleep(0)

            inner.cancel()
            await asyncio.wait_for(until(lambda: state_of(runtime, "a") == "failed"), timeout=10)

            assert "cancelled" in runtime.report()["rows"][0]["error"]
            assert "did not finish starting" in caplog.text  # the kernel logs a task that failed, not one cancelled
            assert _live(runtime) == []
            assert (await client.get("/reads")).status == 404
            assert runtime.web._held == {}

            await runtime.turn_on("a")
            await asyncio.wait_for(until(lambda: state_of(runtime, "a") == "active"), timeout=10)

            assert await (await client.get("/reads")).text() == "written by the hook"

    asyncio.run(scenario())


def test_a_hook_a_stop_cancels_is_no_failure_and_a_dependant_can_come_back(tmp_path: Path) -> None:
    """Its provider's stop ends the hook, and an older service brings the row back, unless that read as a failure."""

    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        rows = [
            ("provider", f"{HERE}:provides_a_thing", False),
            ("dep", f"{HERE}:needs_a_thing_and_starts_slowly", True),
        ]
        runtime = runtime_with(tmp_path, rows)
        runtime.kernel.root.set("thing", "the older value")
        runtime.load()
        runtime.mark_ready()
        await runtime.turn_on("provider")
        await until(lambda: "hook began" in events)
        events.clear()

        await asyncio.wait_for(runtime.turn_off("provider"), timeout=30)
        await until(lambda: "hook began" in events)

        assert state_of(runtime, "dep") == "loading"
        gate.set()
        await until(lambda: state_of(runtime, "dep") == "active")

    asyncio.run(scenario())


def test_a_row_a_press_brought_up_waits_for_its_own_hooks(tmp_path: Path) -> None:
    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        rows = [
            ("dep", f"{HERE}:needs_a_thing_and_starts_slowly", True),
            ("provider", f"{HERE}:provides_a_thing", False),
        ]
        runtime = _running(tmp_path, *rows)
        async with TestClient(TestServer(runtime.web.app)) as client:
            assert (await runtime.turn_on("provider"))["state"] == "active"
            await until(lambda: "hook began" in events)

            assert state_of(runtime, "dep") == "loading"
            assert (await client.get("/reads")).status == 404

            gate.set()
            await until(lambda: state_of(runtime, "dep") == "active")

            assert await (await client.get("/reads")).text() == "written by the hook"

    asyncio.run(scenario())


def test_a_dependant_that_comes_back_waits_for_its_hooks_again(tmp_path: Path) -> None:
    """An older service comes back when its provider goes, so the dependant starts again on a fresh scope."""

    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        gate.set()
        rows = [
            ("provider", f"{HERE}:provides_a_thing", False),
            ("dep", f"{HERE}:needs_a_thing_and_starts_slowly", True),
        ]
        runtime = runtime_with(tmp_path, rows)
        runtime.kernel.root.set("thing", "the older value")
        runtime.load()
        runtime.mark_ready()
        async with TestClient(TestServer(runtime.web.app)) as client:
            await until(lambda: "hook finished" in events)
            await runtime.turn_on("provider")
            events.clear()
            gate.clear()

            await runtime.turn_off("provider")
            await until(lambda: "hook began" in events)

            assert state_of(runtime, "dep") == "loading"
            assert (await client.get("/reads")).status == 404

            gate.set()
            await until(lambda: state_of(runtime, "dep") == "active")

            assert await (await client.get("/reads")).text() == "written by the hook"

    asyncio.run(scenario())


def test_a_dependant_with_no_hooks_joins_while_its_providers_hook_runs(tmp_path: Path) -> None:
    """A limit the spec states. Holding routes back looks only at a row's own hooks, so this one's handler is not held."""

    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        rows = [
            ("provider", f"{HERE}:provides_a_thing_and_starts_slowly", False),
            ("dep", f"{fixture.HERE}:needs_a_thing", True),
        ]
        runtime = _running(tmp_path, *rows)
        async with TestClient(TestServer(runtime.web.app)) as client:
            await runtime.turn_on("provider")
            await until(lambda: "hook began" in events)

            assert state_of(runtime, "provider") == "loading"
            assert (await client.get("/reads")).status == 404
            assert state_of(runtime, "dep") == "active"
            assert (await client.get("/needs")).status == 200

            gate.set()

    asyncio.run(scenario())


def test_a_view_whose_hook_is_added_during_a_hook_holds_the_routes_too(tmp_path: Path) -> None:
    """Any other row's press rebuilds the table meanwhile. If that counted this row as joined, this hook would hold nothing."""

    async def scenario() -> None:
        global gate, first_gate
        gate = asyncio.Event()
        first_gate = asyncio.Event()
        runtime = _running(tmp_path, ("a", f"{HERE}:adds_a_view_during_its_hook", False))
        async with TestClient(TestServer(runtime.web.app)) as client:
            await runtime.turn_on("a")
            await until(lambda: "first hook began" in events)

            runtime.web.publish()
            first_gate.set()
            await until(lambda: "hook began" in events)

            assert (await client.get("/reads")).status == 404
            assert state_of(runtime, "a") == "loading"

            gate.set()
            await until(lambda: state_of(runtime, "a") == "active")

            assert await (await client.get("/reads")).text() == "written by the hook"

    asyncio.run(scenario())


def test_a_row_with_two_views_waits_for_the_hooks_of_both(tmp_path: Path) -> None:
    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        runtime = _running(tmp_path, ("a", f"{HERE}:two_views", False))
        async with TestClient(TestServer(runtime.web.app)) as client:
            await runtime.turn_on("a")
            await until(lambda: "first view started" in events and "hook began" in events)
            await asyncio.sleep(0)

            assert state_of(runtime, "a") == "loading"
            assert (await client.get("/ok")).status == 404

            gate.set()
            await until(lambda: state_of(runtime, "a") == "active")
            assert (await client.get("/ok")).status == 200

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["on_startup", "on_cleanup"])
def test_a_hook_added_to_a_row_already_live_takes_nothing_away(kind: str) -> None:
    """A registrar may add one on first use, long after its routes joined."""

    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        app, kernel = hosted()
        kernel.mark_ready()
        async with TestClient(TestServer(app)) as client:
            _, view = mount_on(kernel, lambda view: view.router.add_get("/ok", ok))
            assert (await client.get("/ok")).status == 200

            getattr(view, kind).append(_hook)
            await asyncio.sleep(0)
            kernel.root["web"].publish()  # any other row's press rebuilds the table, with the hook still running

            assert (await client.get("/ok")).status == 200
            gate.set()

    asyncio.run(scenario())


def _starts_with_the_server(runtime: Any) -> None:
    async def started(_app: Any) -> None:
        runtime.mark_ready()

    runtime.web.app.on_startup.append(started)


def test_at_the_servers_own_start_a_row_still_waits_for_its_hooks_because_the_server_does_not(tmp_path: Path) -> None:
    """The server takes connections as soon as it is up and these hooks are tasks it does not wait for.

    So a handler could run before its hook ended, which is why its route stays off the table until then. These routes
    used to be up from the start, and this test used to pin that.
    """

    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        runtime = runtime_with(tmp_path, [("a", f"{HERE}:starts_slowly", True)])
        runtime.load()
        _starts_with_the_server(runtime)
        assert _live(runtime) == []

        async with TestClient(TestServer(runtime.web.app)) as client:
            await until(lambda: "hook began" in events)

            assert state_of(runtime, "a") == "loading"
            assert _live(runtime) == []
            assert (await client.get("/reads")).status == 404

            gate.set()
            await until(lambda: state_of(runtime, "a") == "active")

            answer = await client.get("/reads")
            assert (answer.status, await answer.text()) == (200, "written by the hook")

    asyncio.run(scenario())


def test_a_hook_that_never_ends_does_not_stop_the_server_starting_and_off_still_ends_it(tmp_path: Path) -> None:
    """No plugin may stop Thomas starting, so the start holds the routes back and does not wait for the hook."""

    async def scenario() -> None:
        global gate
        gate = asyncio.Event()
        runtime = runtime_with(tmp_path, [("a", f"{HERE}:starts_slowly", True)])
        runtime.load()
        app = runtime.web.app
        app.router.add_get("/the-servers-own", ok)
        _starts_with_the_server(runtime)

        async with TestClient(TestServer(app)) as client:
            await until(lambda: "hook began" in events)

            assert (await client.get("/the-servers-own")).status == 200
            assert state_of(runtime, "a") == "loading"

            report = await asyncio.wait_for(runtime.turn_off("a"), timeout=30)

            assert report["state"] == "off"
            assert events == ["hook began", "cleaned up"]

    asyncio.run(scenario())


def test_a_row_whose_hook_fails_as_the_server_starts_never_goes_live_and_can_try_again(tmp_path: Path) -> None:
    async def scenario() -> None:
        global gate, failures_left
        gate = asyncio.Event()
        failures_left = 1
        runtime = runtime_with(tmp_path, [("a", f"{HERE}:starts_slowly", True)])
        runtime.load()
        _starts_with_the_server(runtime)

        async with TestClient(TestServer(runtime.web.app)) as client:
            await until(lambda: "hook began" in events)
            gate.set()
            await until(lambda: state_of(runtime, "a") == "failed")

            assert "this row cannot start" in runtime.report()["rows"][0]["error"]
            assert _live(runtime) == []
            assert (await client.get("/reads")).status == 404
            assert runtime.web._rows == {} and runtime.web._scratch == {} and runtime.web._held == {}

            await runtime.turn_on("a")
            await until(lambda: state_of(runtime, "a") == "active")

            assert await (await client.get("/reads")).text() == "written by the hook"

    asyncio.run(scenario())
