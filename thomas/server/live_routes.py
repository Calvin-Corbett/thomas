"""Web routes that can join and leave a running server.

aiohttp freezes an app's router when it starts, and adding a route after that raises. ``LiveRouter`` keeps a second
table beside the frozen one and looks there first. Everything happens inside ``resolve``, which aiohttp calls before it
builds the middleware chain, so a plugin's route passes through the same auth, CSRF and rate-limit middleware as any
other. Proven on aiohttp 3.14.3 before this was written (2026-10-31).

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import re
from bisect import bisect_left
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aiohttp import hdrs, web
from aiohttp.web_urldispatcher import UrlDispatcher

from thomas.core.kernel import Context, ContextDisposed

log = logging.getLogger(__name__)

_ABSENT: Any = object()
_GROUP_NAME = re.compile(r"\(\?P<\w+>")
_SERVER = SimpleNamespace(label="the server")


@dataclass(frozen=True)
class LiveRow:
    """One recorded ``router`` call, replayed whenever the live table is rebuilt."""

    call: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class LiveRouter(UrlDispatcher):
    _live: UrlDispatcher

    @classmethod
    def adopt(cls, router: UrlDispatcher) -> LiveRouter:
        """Make ``router`` live, in place: what it holds stays, and so does anything already holding it.

        In place rather than through ``web.Application(router=...)``, which aiohttp deprecates, and which would give
        every app that does not ask for a live router a different route to the one a real server takes.
        """
        if not isinstance(router, cls):
            router.__class__ = cls
            router._live = UrlDispatcher()
        return router

    def publish(self, table: UrlDispatcher) -> None:
        """Swap in a new live table. One assignment: a request sees the old table or the new one."""
        self._live = table

    async def resolve(self, request: web.Request) -> Any:
        found = await self._live.resolve(request)
        if found.http_exception is None:
            return found
        fallback = await super().resolve(request)
        if fallback.http_exception is not None and found.http_exception.status == 405:
            return found  # the live table knows this path, so the answer is the wrong method, not "no such page"
        return fallback

    def resources(self) -> Any:
        return [*super().resources(), *self._live.resources()]

    def routes(self) -> Any:
        return [*super().routes(), *self._live.routes()]

    def server_routes(self) -> Any:
        """What the frozen router answers, which the live table must not shadow."""
        return super().routes()


def _path_of(resource: Any) -> str:
    """What a resource answers. ``/things/{id}`` and ``/things/{name}`` answer the same requests, so they are one path."""
    pattern = resource.get_info().get("pattern")
    return resource.canonical if pattern is None else _GROUP_NAME.sub("(", pattern.pattern)


def _hold(holders: dict[str, dict[str, Any]], routes: Iterable[Any], holder: Any) -> None:
    for route in routes:
        if route.resource is not None:
            holders.setdefault(_path_of(route.resource), {})[route.method] = holder


def _held_method(claim: str, held: Collection[str]) -> str | None:
    """The method in ``held`` that claiming ``claim`` on the same path would answer for, if there is one."""
    wanted = _head_last(held) if claim == hdrs.METH_ANY else (claim, hdrs.METH_ANY)
    return next((method for method in wanted if method in held), None)


def _head_last(methods: Iterable[str]) -> list[str]:
    """HEAD after the rest, because ``add_get`` adds it unasked and a reason should name what its author wrote."""
    return sorted(methods, key=lambda method: method == hdrs.METH_HEAD)


class _ExactRoutes:
    """What the server claims exactly, for holding a row's wide pattern to.

    Sorted, so that a pattern is tried only against paths that share its literal start. This runs on the event loop at
    every publish, and most of a row's routes start with a long literal, so they cost a look and almost no regex.
    """

    def __init__(self, server: Iterable[Any]) -> None:
        self._methods: dict[str, set[str]] = {}
        for route in server:
            if route.resource is not None and "path" in route.resource.get_info():
                self._methods.setdefault(route.resource.canonical, set()).add(route.method)
        self._paths = sorted(self._methods)

    def starting(self, literal: str) -> list[str]:
        return self._paths[bisect_left(self._paths, literal) : bisect_left(self._paths, f"{literal}\U0010ffff")]

    def under(self, route: Any) -> str | None:
        """The exact server route this route's pattern would answer in the server's place, if there is one."""
        pattern = route.resource.get_info().get("pattern")
        if pattern is None:
            return None
        for path in self.starting(route.resource.canonical.partition("{")[0]):
            method = _held_method(route.method, self._methods[path])
            if method is not None and pattern.fullmatch(path):
                return f"{method} {path}"
        return None


def _clash(
    ctx: Context, table: UrlDispatcher, holders: Mapping[str, Mapping[str, Any]], exact: _ExactRoutes
) -> RuntimeError | None:
    for route in sorted(table.routes(), key=lambda route: route.method == hdrs.METH_HEAD):  # as ``_head_last``
        claim = f"{route.method} {route.resource.canonical}"
        methods = holders.get(_path_of(route.resource), {})
        if (method := _held_method(route.method, methods)) is not None:
            return RuntimeError(f"{ctx.label} claims {claim}, which {methods[method].label} already holds")
        if (covered := exact.under(route)) is not None:
            return RuntimeError(
                f"{ctx.label} claims {claim}, which covers {covered}, and the server already holds that"
            )
    return None


def _shared_routes(tables: Mapping[Context, UrlDispatcher], server: Collection[Any]) -> list[tuple[Context, Exception]]:
    """The plugins that claim a route already held, each with its reason, because the first holder would answer for both.

    aiohttp cannot be left to notice. It compares a new path only with the last one it added, so with any route between
    the two claims both plugins would read active and the second's handler would never run. The server comes first: the
    live table is looked at first, so a row matching its route would answer in the server's place with no error. That
    covers what the server claims exactly, whether a row claims the same path or a pattern wide enough to answer it. A
    wide pattern of the server's own is out of reach here. A plugin is not compared with itself, because a real app takes
    one that repeats its own route, and one that is refused holds nothing.
    """
    holders: dict[str, dict[str, Any]] = {}
    _hold(holders, server, _SERVER)
    exact = _ExactRoutes(server)
    refused: list[tuple[Context, Exception]] = []
    for ctx, table in tables.items():
        if (clash := _clash(ctx, table, holders, exact)) is not None:
            refused.append((ctx, clash))
        else:
            _hold(holders, table.routes(), ctx)
    return refused


def _counted(ctx: Context, path: str, handler: Callable[..., Any]) -> Callable[..., Any]:
    """A handler a stop will wait for. A request that resolved just before its plugin stopped gets a 404.

    aiohttp's task has no name a person could use, and a forced stop that goes on without a handler can give only a name.
    So the task carries the route while the handler runs. aiohttp gives each request a task of its own today, so its own
    name going back is only care, in case a later version shares one.
    """

    @functools.wraps(handler)
    async def counted(request: web.Request) -> web.StreamResponse:
        task = asyncio.current_task()
        its_own_name = task.get_name()
        task.set_name(f"{request.method} {path}")
        try:
            async with ctx.busy():
                return await handler(request)
        except ContextDisposed:
            raise web.HTTPNotFound() from None
        finally:
            task.set_name(its_own_name)

    return counted


class _Streams:
    """Handlers that end only when told to, such as an event stream an open page is reading.

    A stop waits for running work, so one open page would hold the off switch for ever. These end when the stop begins
    instead, which the page sees as a dropped connection.
    """

    def __init__(self) -> None:
        self.named: set[str] = set()
        self.registered: set[str] = set()
        self._running: set[asyncio.Task[Any]] = set()
        self._ended = False

    def wrap(self, path: str, handler: Callable[..., Any]) -> Callable[..., Any]:
        if path not in self.named:
            return handler
        self.registered.add(path)

        @functools.wraps(handler)
        async def stream(request: web.Request) -> web.StreamResponse:
            if self._ended:  # it resolved just before the stop began, and nothing would ever end it
                raise web.HTTPNotFound()
            task = asyncio.current_task()
            self._running.add(task)
            try:
                return await handler(request)
            finally:
                self._running.discard(task)

        return stream

    def end(self) -> None:
        self._ended = True
        for task in list(self._running):
            task.cancel()


class _RecordingRouter:
    """What a plugin's registrar sees as ``app.router``. Anything it does not have raises, so nothing is lost quietly.

    Each call lands on a scratch table too. A bad route then raises inside the registrar, as it does on a real app, and
    the registrar gets back what a real router would have handed it.
    """

    def __init__(
        self, ctx: Context, rows: list[LiveRow], scratch: UrlDispatcher, live: LiveRouter, streams: _Streams
    ) -> None:
        self._ctx = ctx
        self._rows = rows
        self._scratch = scratch
        self._live = live
        self._streams = streams

    def _add(self, call: str, *args: Any, **kwargs: Any) -> Any:
        made = getattr(self._scratch, call)(*args, **kwargs)
        self._rows.append(LiveRow(call, args, kwargs))
        return made

    def _record(self, call: str, *leading: Any, handler: Callable[..., Any], **kwargs: Any) -> Any:
        path = leading[-1]
        return self._add(call, *leading, _counted(self._ctx, path, self._streams.wrap(path, handler)), **kwargs)

    def add_get(self, path: str, handler: Callable[..., Any], **kwargs: Any) -> Any:
        return self._record("add_get", path, handler=handler, **kwargs)

    def add_post(self, path: str, handler: Callable[..., Any], **kwargs: Any) -> Any:
        return self._record("add_post", path, handler=handler, **kwargs)

    def add_put(self, path: str, handler: Callable[..., Any], **kwargs: Any) -> Any:
        return self._record("add_put", path, handler=handler, **kwargs)

    def add_patch(self, path: str, handler: Callable[..., Any], **kwargs: Any) -> Any:
        return self._record("add_patch", path, handler=handler, **kwargs)

    def add_delete(self, path: str, handler: Callable[..., Any], **kwargs: Any) -> Any:
        return self._record("add_delete", path, handler=handler, **kwargs)

    def add_route(self, method: str, path: str, handler: Callable[..., Any], **kwargs: Any) -> Any:
        return self._record("add_route", method, path, handler=handler, **kwargs)

    def add_routes(self, routes: Iterable[Any]) -> list[Any]:
        """Through ``RouteDef.register``, so each route keeps what it asked for, such as ``allow_head``."""
        registered: list[Any] = []
        for route in routes:
            registered.extend(route.register(self))
        return registered

    def add_static(self, prefix: str, path: Any, **kwargs: Any) -> Any:
        """A folder of files. A file on its way out does not count as running work, so a stop does not wait for it."""
        return self._add("add_static", prefix, path, **kwargs)

    def resources(self) -> list[Any]:
        """All the server has, then what this plugin has added, which is not live until its mount publishes it."""
        return [*self._live.resources(), *self._scratch.resources()]


class _Hooks:
    """What a plugin's registrar sees as ``app.on_startup``, ``app.on_cleanup`` or ``app.cleanup_ctx``.

    ``frozen`` reads False while the plugin is being set up, even on a server that froze long ago, because two
    registrars skip their hooks on a frozen app and a plugin turned on later would then never start.
    """

    def __init__(self, added: Callable[[], None]) -> None:
        self.frozen = False
        self._hooks: list[Any] = []
        self._added = added

    def append(self, hook: Any) -> None:
        if self.frozen:
            raise RuntimeError("these hooks have already run, so this one never would")
        self._hooks.append(hook)
        self._added()

    def __iter__(self) -> Iterator[Any]:
        return iter(self._hooks)


def _put(state: dict[Any, Any], key: Any, value: Any) -> None:
    if value is _ABSENT:
        state.pop(key, None)
    else:
        state[key] = value


@dataclass
class _Writers:
    """Who has written one app key, oldest first, so that a key leaves with its last writer.

    Shared by every plugin, because what one saw when it first wrote may be a value another has since taken away. A
    write from outside the plugins is kept here too, with no owner, because that one never leaves.
    """

    before: Any
    writes: list[tuple[PluginApp | None, Any]] = field(default_factory=list)

    def newest(self) -> Any:
        return self.writes[-1][1] if self.writes else self.before

    def write(self, owner: PluginApp, value: Any, found: Any) -> None:
        if found is not self.newest():
            self.writes.append((None, found))
        self.leave(owner)
        self.writes.append((owner, value))

    def leave(self, owner: PluginApp) -> None:
        self.writes = [write for write in self.writes if write[0] is not owner]

    def belongs_to_no_plugin(self) -> bool:
        return all(owner is None for owner, _ in self.writes)


def _cleanup_context(make: Callable[..., Any], app: PluginApp) -> Any:
    """What a ``cleanup_ctx`` entry opens: an async generator with one ``yield``, or a context manager it returns."""
    made = make(app)
    if isinstance(made, contextlib.AbstractAsyncContextManager):
        return made
    return contextlib.asynccontextmanager(make)(app)


class PluginApp(MutableMapping[Any, Any]):
    """``app`` as a plugin's registrar sees it.

    Reads reach the real app. Writes do too, because handlers read ``request.app``, and stopping takes them back. They
    go straight to ``app._state``: the app froze when the server started, and writing through ``app[key]`` after that
    raises aiohttp's DeprecationWarning, which warning-as-error runs turn into a 500.

    Routes go to the plugin's rows. Hooks run when the plugin starts and stops rather than when the server does, because
    a plugin turned on later would miss the server's. They are handed this view as their ``app``, so what they write
    leaves with the plugin too.
    """

    # As on the real app. Registrars key their caches on it, which a mapping's ``__eq__`` would otherwise forbid.
    __eq__ = object.__eq__
    __hash__ = object.__hash__

    def __init__(self, service: WebService, router: _RecordingRouter, ctx: Context) -> None:
        self._service = service
        self._app = service.app
        self.router = router
        self._ctx = ctx
        self._writers = service.writers
        self._wrote: set[Any] = set()
        self._opened: list[Any] = []
        self._hooked = False
        self.on_startup = _Hooks(self._start_hook_added)
        self.on_cleanup = _Hooks(self._hook_added)
        self.cleanup_ctx = _Hooks(self._start_hook_added)

    def __getitem__(self, key: Any) -> Any:
        return self._app[key]

    def __setitem__(self, key: Any, value: Any) -> None:
        self._write(key, value)

    def __delitem__(self, key: Any) -> None:
        if key not in self._app:
            raise KeyError(key)
        self._write(key, _ABSENT)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._app)

    def __len__(self) -> int:
        return len(self._app)

    def _write(self, key: Any, value: Any) -> None:
        """Change a key and have stopping take it back: one undo a key, because handlers may write one on every call."""
        if key not in self._wrote:
            self._ctx.effect(functools.partial(self._take_back, key))
            self._wrote.add(key)
        state = self._app._state
        found = state.get(key, _ABSENT)
        self._writers.setdefault(key, _Writers(found)).write(self, value, found)
        _put(state, key, value)

    def _take_back(self, key: Any) -> None:
        """Leave the key to the newest writer still here, or as it was before any of them, or gone."""
        self._wrote.discard(key)
        state = self._app._state
        writers = self._writers[key]
        # Only if no one has written since. If someone wrote on top, theirs wins: an unwind must never clobber a writer.
        untouched = state.get(key, _ABSENT) is writers.newest()
        writers.leave(self)
        if untouched:
            _put(state, key, writers.newest())
        if writers.belongs_to_no_plugin():
            del self._writers[key]

    def add_routes(self, routes: Iterable[Any]) -> list[Any]:
        return self.router.add_routes(routes)

    def _start_hook_added(self) -> None:
        self._service.hold(self._ctx, self)
        self._hook_added()

    def _hook_added(self) -> None:
        if not self._hooked:
            self._hooked = True
            self._ctx.on_stopped(self._clean_up)
            self._ctx.on_ready(self._begin)

    def _begin(self) -> None:
        # A task, which waits its turn, so on a plugin turned on later ``apply`` finishes adding hooks before any runs.
        self._ctx.task(self._start, name="startup hooks").add_done_callback(self._started)

    async def _start(self) -> None:
        """In aiohttp's order: each ``cleanup_ctx`` up to its ``yield``, then ``on_startup``, one at a time.

        Hooks never run for a mount that failed: this is an owned task, so losing the scope cancels it before its first turn.
        """
        try:
            for make in self.cleanup_ctx:
                opened = _cleanup_context(make, self)
                await opened.__aenter__()
                self._opened.append(opened)
            for hook in self.on_startup:
                await hook(self)
        finally:
            self.on_startup.frozen = self.cleanup_ctx.frozen = True

    def _started(self, task: asyncio.Task[Any]) -> None:
        """Its hooks are done, so routes they were holding back can join.

        A hook that fails reads ``failed`` with its reason, and the kernel has logged it. The plugin stays plugged in,
        because only ``stop`` can run its cleanups, and turning it off does that. Routes it was holding back never join.

        A stop or a scope going away cancels these hooks on purpose, and neither is a failure. A hook can also end
        cancelled with nothing stopping, by awaiting something that was cancelled elsewhere. That is a failure, or the
        plugin would read ``loading`` for ever with no reason.
        """
        cancelled = task.cancelled()
        problem = RuntimeError("a startup hook was cancelled with no stop") if cancelled else task.exception()
        if problem is None:
            self._service.let_join(self._ctx, self)
            return
        for fork in self._ctx.kernel.mounted():
            if fork.ctx is self._ctx and not (cancelled and fork.stopping):
                log.warning("%s did not finish starting: %s", self._ctx.label, problem)
                fork.error = problem
                self._service.never_joins(self._ctx)

    async def _clean_up(self) -> None:
        """Hand each hook to the stop as a step of its own, so one that fails or hangs costs only itself.

        Stop steps run newest first, so ``on_cleanup`` goes on backwards, because aiohttp runs that oldest first, and
        ``cleanup_ctx`` goes on last, because aiohttp closes those first, newest first. Read here rather than as hooks
        are added, because a registrar may add one on first use, long after startup.
        """
        self.on_cleanup.frozen = True
        for hook in reversed(list(self.on_cleanup)):
            self._ctx.on_stopped(functools.partial(hook, self))
        for opened in self._opened:
            self._ctx.on_stopped(functools.partial(opened.__aexit__, None, None, None))


class WebService:
    """The ``web`` service: what a plugin needs from the server shell, keeping HTTP out of the kernel."""

    def __init__(
        self,
        app: web.Application,
        config: Any,
        *,
        require_api_access: Callable[..., Any] | None,
        read_json: Callable[..., Any] | None,
        require_loopback: Callable[..., Any] | None = None,
        web_dir: Path | None = None,
    ) -> None:
        self.app = app
        self.config = config
        self.require_api_access = require_api_access
        self.read_json = read_json
        self.require_loopback = require_loopback
        self.web_dir = web_dir
        self._router = LiveRouter.adopt(app.router)
        self._rows: dict[Context, list[LiveRow]] = {}
        self._scratch: dict[Context, UrlDispatcher] = {}
        self._streams: dict[Context, _Streams] = {}
        self._held: dict[Context, set[PluginApp]] = {}
        self._joined: set[Context] = set()
        self.writers: dict[Any, _Writers] = {}
        self._rebuilds: list[Callable[[], None]] = []

    def view(self, ctx: Context, *, streams: Iterable[str] = (), keep_routes: bool = False) -> PluginApp:
        """An app-shaped wrapper. Its routes leave first when the plugin stops, so new work stops arriving.

        ``streams`` names the paths whose handlers end only when told to, and they are ended when the stop begins. A
        stream left out holds the off switch for as long as a page has it open.

        ``keep_routes`` keeps the routes until running work has ended, for a plugin whose work calls back in through
        them and would fail on a 404 during the wait.
        """
        rows = self._rows.setdefault(ctx, [])
        scratch = self._scratch.setdefault(ctx, UrlDispatcher())
        ending = self._streams.setdefault(ctx, _Streams())
        ending.named.update(streams)

        def leave() -> None:
            if self._forget(ctx):
                self.publish()

        async def stop_arriving() -> None:
            ending.end()
            if not keep_routes:
                leave()

        ctx.on_drain(stop_arriving)
        ctx.effect(leave)
        return PluginApp(self, _RecordingRouter(ctx, rows, scratch, self._router, ending), ctx)

    def after_publish(self, rebuild: Callable[[], None]) -> None:
        """Call ``rebuild`` each time the live table changes, for anything that keeps its own list of routes.

        One that raises is logged and costs only itself, because the table has changed by then and a press has worked.
        """
        self._rebuilds.append(rebuild)

    def hold(self, ctx: Context, view: PluginApp) -> None:
        """Keep routes that have never been live off the table until this view's startup hooks end.

        A real server finishes ``on_startup`` before it takes a connection, so a handler may lean on what a hook set up.
        These hooks are tasks no server waits for, because no plugin may stop Thomas starting, so this holds while the
        server itself starts too: it takes connections as soon as it is up. Routes already live stay, because a hook
        added on first use is no reason to take them away.
        """
        if ctx not in self._joined:
            self._held.setdefault(ctx, set()).add(view)

    def starting(self, ctx: Context) -> bool:
        """True while startup hooks are holding a plugin's routes back."""
        return ctx in self._held

    def let_join(self, ctx: Context, view: PluginApp) -> None:
        waiting = self._held.get(ctx)
        if waiting is None:
            return
        waiting.discard(view)
        if not waiting:
            del self._held[ctx]
            self.publish()

    def never_joins(self, ctx: Context) -> None:
        """A startup hook failed. Routes it was holding back leave the table with their claims, for a later try to make."""
        if ctx in self._held:
            self._forget(ctx)

    def _forget(self, ctx: Context) -> bool:
        """Drop all a plugin has on the table. True if it had any."""
        self._streams.pop(ctx, None)
        self._scratch.pop(ctx, None)
        self._held.pop(ctx, None)
        self._joined.discard(ctx)
        return self._rows.pop(ctx, None) is not None

    def _refuse(self, ctx: Context, problem: Exception, *, strict: bool) -> None:
        """Fail the plugin at fault, whoever's press found it. It holds no claim and none of its routes join.

        Its work carries on until it is turned off, because only a stop can end that and a stop has to be awaited. So it
        reads ``failed`` with the reason, as one whose startup hook failed does, and turning it off or on again cleans up.
        """
        log.warning("%s left the route table: %s", ctx.label, problem)
        self._forget(ctx)
        for fork in ctx.kernel.mounted():
            if fork.ctx is ctx:
                fork.error = problem
        if strict:
            raise problem

    def _table(self, *, strict: bool) -> UrlDispatcher:
        """A table of every plugin that can join. Replaying can fail on its own account, as a folder it serves can go."""
        while True:
            table = UrlDispatcher()
            for ctx, rows in self._rows.items():
                if ctx in self._held:
                    continue
                try:
                    for row in rows:
                        getattr(table, row.call)(*row.args, **row.kwargs)
                except Exception as exc:
                    # Broad catch: a plugin's routes are its own code, and only it may pay for them.
                    log.warning("Routes for %s could not be rebuilt: %s", ctx.label, exc)
                    self._refuse(ctx, exc, strict=False)
                    if strict:
                        raise
                    break  # this table holds part of a plugin that has gone
            else:
                return table

    def publish(self, *, strict: bool = False) -> None:
        """Swap in the live table. A plugin whose routes cannot join fails alone, and the rest join as ever.

        So this never raises for a plugin's routes, or for what keeps a list of them, whichever press got here, unless
        ``strict`` asks to hear about it.
        """
        refused: list[tuple[Context, Exception]] = []
        for ctx, streams in self._streams.items():
            if unregistered := streams.named - streams.registered:
                refused.append(
                    (ctx, ValueError(f"{ctx.label} names streams it never registered: {sorted(unregistered)}"))
                )
        for ctx, problem in refused:
            self._refuse(ctx, problem, strict=strict)
        for ctx, problem in _shared_routes(self._scratch, self._router.server_routes()):
            self._refuse(ctx, problem, strict=strict)
        self._router.publish(self._table(strict=strict))
        self._joined.update(ctx for ctx in self._rows if ctx not in self._held)
        for rebuild in self._rebuilds:
            try:
                rebuild()
            except Exception:
                # Broad catch: this list is someone else's code, and the press that got here has already worked.
                log.exception("A rebuild after the route table changed failed, so what it keeps is out of date")
                if strict:
                    raise


__all__ = ["LiveRouter", "LiveRow", "PluginApp", "WebService"]
