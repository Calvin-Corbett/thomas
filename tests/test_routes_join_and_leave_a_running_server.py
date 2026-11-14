"""A route can join and leave a server whose router aiohttp has frozen, with every middleware still in front of it."""

from __future__ import annotations

import asyncio
import warnings

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from aiohttp.web_urldispatcher import UrlDispatcher

from thomas.core.kernel import Kernel, stop
from thomas.server.live_routes import LiveRouter, WebService


async def _until(check) -> None:
    while not check():
        await asyncio.sleep(0.01)


async def _hello(request: web.Request) -> web.Response:
    return web.Response(text=f"hello {request.match_info['who']}")


async def _locked(_request: web.Request) -> web.Response:
    return web.Response(text="locked")


def _plugin(ctx, config) -> None:
    app = ctx["web"].view(ctx)
    app.router.add_get("/plugin/{who}", _hello)
    app.router.add_post("/plugin/{who}", _hello)
    app.router.add_route("*", "/any", _locked)


_plugin.name = "routes"
_plugin.inject = ("web",)


def _hosted(*more_middleware) -> tuple[web.Application, WebService, Kernel]:
    @web.middleware
    async def guard(request: web.Request, handler):
        if request.headers.get("X-Block"):
            return web.Response(status=403, text="blocked")
        return await handler(request)

    app = web.Application(middlewares=[guard, *more_middleware])
    app.router.add_get("/locked", _locked)
    service = WebService(app, None, require_api_access=lambda request: None, read_json=None)
    kernel = Kernel()
    kernel.root.set("web", service)
    return app, service, kernel


def test_a_router_becomes_live_in_place_and_keeps_what_it_holds() -> None:
    app = web.Application()
    router = app.router
    router.add_get("/before", _locked)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        WebService(app, None, require_api_access=None, read_json=None)

    assert app.router is router  # anything already holding it keeps working
    assert isinstance(router, LiveRouter)
    assert isinstance(router, UrlDispatcher)
    assert "/before" in {resource.canonical for resource in router.resources()}
    assert LiveRouter.adopt(router) is router  # a second app's service changes nothing


def test_a_route_joins_and_leaves_a_frozen_server() -> None:
    async def scenario() -> None:
        app, service, kernel = _hosted()
        async with TestClient(TestServer(app)) as client:
            assert app.router.frozen
            assert (await client.get("/plugin/calvin")).status == 404

            fork = kernel.mount(_plugin)
            service.publish()

            joined = await client.get("/plugin/calvin")
            assert (joined.status, await joined.text()) == (200, "hello calvin")
            assert (await client.get("/locked")).status == 200

            await stop(fork)

            assert (await client.get("/plugin/calvin")).status == 404
            assert (await client.get("/locked")).status == 200

    asyncio.run(scenario())


def test_middleware_stands_in_front_of_a_live_route() -> None:
    async def scenario() -> None:
        app, service, kernel = _hosted()
        async with TestClient(TestServer(app)) as client:
            kernel.mount(_plugin)
            service.publish()

            refused = await client.get("/plugin/calvin", headers={"X-Block": "1"})
            assert refused.status == 403

    asyncio.run(scenario())


def test_a_live_path_with_the_wrong_method_is_405_not_404() -> None:
    async def scenario() -> None:
        app, service, kernel = _hosted()
        async with TestClient(TestServer(app)) as client:
            kernel.mount(_plugin)
            service.publish()

            assert (await client.put("/plugin/calvin")).status == 405

    asyncio.run(scenario())


def test_listing_routes_sees_both_tables() -> None:
    app, service, kernel = _hosted()
    kernel.mount(_plugin)
    service.publish()

    canonical = {resource.canonical for resource in app.router.resources()}
    methods = {(route.method, route.resource.canonical) for route in app.router.routes()}

    assert {"/locked", "/plugin/{who}", "/any"} <= canonical
    assert ("POST", "/plugin/{who}") in methods
    assert ("HEAD", "/plugin/{who}") in methods  # add_get means the same here as on the frozen router


def test_a_request_that_started_finishes_while_new_ones_get_a_404() -> None:
    async def scenario() -> None:
        release = asyncio.Event()

        async def slow(_request: web.Request) -> web.Response:
            await release.wait()
            return web.Response(text="finished")

        def plugin(ctx, config) -> None:
            ctx["web"].view(ctx).router.add_get("/slow", slow)

        plugin.name = "slow"
        plugin.inject = ("web",)
        app, service, kernel = _hosted()
        async with TestClient(TestServer(app)) as client:
            fork = kernel.mount(plugin)
            service.publish()
            running = asyncio.create_task(client.get("/slow"))
            await _until(lambda: fork.ctx.working == 1)

            stopping = asyncio.create_task(stop(fork))
            await _until(lambda: fork.state == "unloading")

            assert (await client.get("/slow")).status == 404

            release.set()
            await stopping
            answer = await running
            assert (answer.status, await answer.text()) == (200, "finished")

    asyncio.run(scenario())


def test_a_stop_step_waits_for_a_request_in_flight() -> None:
    async def scenario() -> None:
        order = []
        release = asyncio.Event()

        async def slow(_request: web.Request) -> web.Response:
            await release.wait()
            order.append("request finished")
            return web.Response(text="finished")

        async def clean_up() -> None:
            order.append("cleaned up")

        def plugin(ctx, config) -> None:
            ctx["web"].view(ctx).router.add_get("/slow", slow)
            ctx.on_stopped(clean_up)

        plugin.name = "slow"
        plugin.inject = ("web",)
        app, service, kernel = _hosted()
        async with TestClient(TestServer(app)) as client:
            fork = kernel.mount(plugin)
            service.publish()
            running = asyncio.create_task(client.get("/slow"))
            await _until(lambda: fork.ctx.working == 1)

            stopping = asyncio.create_task(stop(fork))
            await _until(lambda: fork.state == "unloading")

            assert (await client.get("/slow")).status == 404
            assert order == []

            release.set()
            await stopping
            answer = await running

            assert (answer.status, await answer.text()) == (200, "finished")
            assert order == ["request finished", "cleaned up"]

    asyncio.run(scenario())


def test_a_request_still_in_middleware_when_teardown_begins_gets_a_404_not_a_torn_down_plugin() -> None:
    """It resolved before the route left, and nothing counted it, so the wait for running work could not see it."""

    async def scenario() -> None:
        handled = []
        in_middleware = asyncio.Event()
        let_through = asyncio.Event()
        answered = asyncio.Event()

        @web.middleware
        async def held(request: web.Request, handler):
            in_middleware.set()
            await let_through.wait()
            return await handler(request)

        async def late(_request: web.Request) -> web.Response:
            handled.append("ran during teardown")
            return web.Response(text="ran")

        async def clean_up() -> None:
            let_through.set()
            await answered.wait()

        def plugin(ctx, config) -> None:
            ctx["web"].view(ctx).router.add_get("/late", late)
            ctx.on_stopped(clean_up)

        plugin.name = "late"
        plugin.inject = ("web",)
        app, service, kernel = _hosted(held)
        async with TestClient(TestServer(app)) as client:
            fork = kernel.mount(plugin)
            service.publish()
            running = asyncio.create_task(client.get("/late"))
            await in_middleware.wait()

            stopping = asyncio.create_task(stop(fork))
            answer = await running
            answered.set()
            await stopping

            assert answer.status == 404
            assert handled == []

    asyncio.run(scenario())


def test_a_registrar_that_needs_what_a_view_cannot_give_is_told_plainly() -> None:
    """A middleware cannot join a frozen app, so a view has no list to add one to, and nothing is lost quietly."""
    _, _, kernel = _hosted()

    def plugin(ctx, config) -> None:
        ctx["web"].view(ctx).middlewares.append(None)

    plugin.name = "adds-middleware"
    plugin.inject = ("web",)

    with pytest.raises(AttributeError):
        kernel.mount(plugin)
