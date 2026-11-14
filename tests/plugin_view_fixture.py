"""Helpers and plugins for tests/test_a_plugin_sees_a_real_app.py and tests/test_a_row_switches_on_a_running_server.py."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aiohttp import web

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.core.kernel import Fork, Kernel
from thomas.server.live_routes import PluginApp, WebService
from thomas.server.runtime_plugins import RuntimePlugins

WRITTEN = web.AppKey("written_by_a_plugin", str)
HERE = __name__

applied: list[Any] = []
events: list[str] = []
imported_on: list[int] = []
import_gate = threading.Event()
release_slow = threading.Event()


def reset() -> None:
    applied.clear()
    events.clear()
    imported_on.clear()
    import_gate.clear()
    release_slow.clear()


def config_in(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "memory")),
    )


def profile_at(path: Path, rows: list[tuple[str, str, bool]]) -> Path:
    text = 'name = "test"\n'
    for row_id, entry, enabled in rows:
        text += f'[[row]]\nid = "{row_id}"\nentry = "{entry}"\nenabled = {str(enabled).lower()}\n'
    path.write_text(text, encoding="utf-8")
    return path


def runtime_with(tmp_path: Path, rows: list[tuple[str, str, bool]]) -> RuntimePlugins:
    profile = profile_at(tmp_path / "profile.toml", rows)
    service = WebService(web.Application(), None, require_api_access=lambda request: None, read_json=None)
    return RuntimePlugins(service, profile_path=profile, choices_path=tmp_path / "plugins" / "choices.json")


def row_here(module: str, name: str, *, on: bool = True) -> tuple[str, str, bool]:
    """A row named for the attribute of ``module`` that holds its plugin."""
    return (name, f"{module}:{name}", on)


def state_of(runtime: RuntimePlugins, row_id: str) -> str:
    return next(row["state"] for row in runtime.report()["rows"] if row["id"] == row_id)


def hosted(*middlewares: Any) -> tuple[web.Application, Kernel]:
    app = web.Application(middlewares=list(middlewares))
    kernel = Kernel()
    kernel.root.set("web", WebService(app, None, require_api_access=lambda request: None, read_json=None))
    return app, kernel


def mount_on(kernel: Kernel, build: Any = None, **options: Any) -> tuple[Fork, PluginApp]:
    """Mount a plugin that hands its view to ``build``, then put its routes live, as the switch does."""
    views: list[PluginApp] = []

    def apply(ctx: Any, config: Any) -> None:
        views.append(ctx["web"].view(ctx, **options))
        if build is not None:
            build(views[0])

    fork = kernel.mount(SimpleNamespace(name="row", inject=("web",), apply=apply))
    kernel.root["web"].publish()
    if fork.error is not None:
        raise fork.error
    return fork, views[0]


async def until(check: Any) -> None:
    while not check():
        await asyncio.sleep(0.01)


async def rows_once_started(runtime: RuntimePlugins) -> list[dict[str, Any]]:
    """Every row, once none is running its startup hooks, which a server does not wait for."""
    await until(lambda: all(row["state"] != "loading" for row in runtime.report()["rows"]))
    return runtime.report()["rows"]


async def ok(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


def waits_for(gate: asyncio.Event) -> Any:
    async def handler(_request: web.Request) -> web.Response:
        await gate.wait()
        events.append("request finished")
        return web.Response(text="finished")

    return handler


def records(text: str) -> Any:
    async def hook(_app: Any) -> None:
        events.append(text)

    return hook


async def read_written(request: web.Request) -> web.Response:
    return web.Response(text=request.app[WRITTEN])


async def event_stream(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse()
    await response.prepare(request)
    await response.write(b"data: open\n\n")
    try:
        await asyncio.Event().wait()
    finally:
        events.append("stream closed")
    return response


async def socket_stream(request: web.Request) -> web.WebSocketResponse:
    socket = web.WebSocketResponse()
    await socket.prepare(request)
    await socket.send_str("open")
    try:
        await asyncio.Event().wait()
    finally:
        events.append("stream closed")
    return socket


class _Named:
    """Rows name a module attribute, so the plugins a switch test needs live here."""

    inject = ("web",)

    def __init__(self, name: str, build: Any) -> None:
        self.name = name
        self._build = build

    def apply(self, ctx: Any, config: Any) -> None:
        applied.append(self.name)
        self._build(ctx["web"].view(ctx))


def _writes_the_key(view: PluginApp) -> None:
    view[WRITTEN] = "from the plugin"
    view.router.add_get("/written", read_written)


def _claims_a_route(view: PluginApp) -> None:
    view.router.add_get("/claimed", ok)


def _claims_a_route_and_another_after_it(view: PluginApp) -> None:
    view.router.add_get("/claimed", ok)
    view.router.add_get("/first-only", ok)


def _adds_hooks(view: PluginApp) -> None:
    view.on_startup.append(records("started"))
    view.on_cleanup.append(records("cleaned up"))


def _everything(view: PluginApp) -> None:
    _adds_hooks(view)
    _writes_the_key(view)
    view.setdefault(WRITTEN, "ignored")


class Adds:
    """A row with one route, for whatever may or may not join the table. ``needs`` are services it waits for."""

    def __init__(self, method: str, path: str, *needs: str) -> None:
        self.name = f"adds {method} {path}"
        self.inject = ("web", *needs)
        self._method = method
        self._path = path

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx).router.add_route(self._method, self._path, ok)


class _NamesAStreamItNeverRegisters:
    name = "typo"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx, streams=("/typo/in/the/name",)).router.add_get("/events", event_stream)


async def _works_forever() -> None:
    await asyncio.Event().wait()


class _WorksThenClaimsARoute:
    name = "works-then-claims"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        ctx.on_ready(lambda: ctx.task(_works_forever, name="work"))
        ctx["web"].view(ctx).router.add_get("/claimed", ok)


class _WorksThenRaises:
    name = "works-then-raises"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        ctx.on_ready(lambda: ctx.task(_works_forever, name="work"))
        raise OSError("apply fell over after its work began")


class _ProvidesAThing:
    name = "provides-a-thing"
    inject = ()

    def apply(self, ctx: Any, config: Any) -> None:
        ctx.set("thing", "the newer value")


class _ProvidesAThingThenClaimsARoute:
    name = "provides-then-claims"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        ctx.set("thing", "the newer value")
        ctx["web"].view(ctx).router.add_get("/claimed", ok)


class _LeavesAThingBehindThenClaimsARoute:
    """On its way out it leaves the service in place, so what depends on it outlives it."""

    name = "leaves-a-thing-behind"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        async def leave_one_behind() -> None:
            ctx.kernel.root.set("thing", "what it left behind")

        ctx.set("thing", "the newer value")
        ctx.on_stopped(leave_one_behind)
        ctx["web"].view(ctx).router.add_get("/claimed", ok)


class _NeedsAThing:
    name = "needs-a-thing"
    inject = ("web", "thing")

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx).router.add_get("/needs", ok)


async def _held_open(_request: web.Request) -> web.Response:
    events.append("slow began")
    await until(release_slow.is_set)
    return web.Response(text="finished")


class _NeedsAThingAndIsBusy:
    name = "needs-a-thing-and-is-busy"
    inject = ("web", "thing")

    def apply(self, ctx: Any, config: Any) -> None:
        applied.append(self.name)
        view = ctx["web"].view(ctx)
        view.on_cleanup.append(records("cleaned up"))
        view.router.add_get("/needs", ok)
        view.router.add_get("/slow", _held_open)


writes_a_key = _Named("writes-a-key", _writes_the_key)
claims_a_route = _Named("claims-a-route", _claims_a_route)
claims_it_too = _Named("claims-it-too", _claims_a_route)
claims_it_and_another = _Named("claims-it-and-another", _claims_a_route_and_another_after_it)
adds_hooks = _Named("adds-hooks", _adds_hooks)
everything = _Named("everything", _everything)
names_a_stream_it_never_registers = _NamesAStreamItNeverRegisters()
works_then_claims_a_route = _WorksThenClaimsARoute()
works_then_raises = _WorksThenRaises()
provides_a_thing = _ProvidesAThing()
provides_a_thing_then_claims_a_route = _ProvidesAThingThenClaimsARoute()
leaves_a_thing_behind_then_claims_a_route = _LeavesAThingBehindThenClaimsARoute()
needs_a_thing = _NeedsAThing()
needs_a_thing_and_is_busy = _NeedsAThingAndIsBusy()


class RowsStartedFirst:
    """For an ``AioHTTPTestCase`` that builds the real app: no test body runs before the rows have finished starting.

    A row's routes join once its startup steps end, and no server waits for those steps, so a request sent straight away
    can get a 404 for a route that is about to join. List this class before ``AioHTTPTestCase``.
    """

    async def asyncSetUp(self) -> None:
        from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

        await super().asyncSetUp()  # type: ignore[misc]
        await rows_once_started(self.app[APP_RUNTIME_PLUGINS])  # type: ignore[attr-defined]
