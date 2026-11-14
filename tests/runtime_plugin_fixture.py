"""Plugins for tests/test_your_choices_decide_which_plugins_load.py."""

from __future__ import annotations

import asyncio

from aiohttp import web

gate: asyncio.Event | None = None
failures_left = 0  # how many starts fail before one works
cleaned_up: list[str] = []


def _one_failure() -> None:
    global failures_left
    if failures_left > 0:
        failures_left -= 1
        raise RuntimeError("the port is taken")


async def _startup_hook(_app: object) -> None:
    _one_failure()


async def _cleanup_hook(_app: object) -> None:
    cleaned_up.append("cleaned up")


async def _hello(request: web.Request) -> web.Response:
    return web.Response(text=f"hello {request.match_info['who']}")


async def _slow(_request: web.Request) -> web.Response:
    await gate.wait()
    return web.Response(text="finished")


class _Routes:
    name = "routes-fixture"
    inject = ("web",)

    def apply(self, ctx, config) -> None:
        app = ctx["web"].view(ctx)
        app.router.add_get("/fixture/hello/{who}", _hello)
        app.router.add_get("/fixture/slow", _slow)


class _Quiet:
    name = "quiet-fixture"
    inject = ()

    def apply(self, ctx, config) -> None:
        return None


class _Explodes:
    name = "explodes-fixture"
    inject = ()

    def apply(self, ctx, config) -> None:
        raise RuntimeError("boom")


class _FailsStarting:
    """Applies cleanly and fails once the server is up, so the failed fork stays with no scope left."""

    name = "fails-starting"
    inject = ()

    def apply(self, ctx, config) -> None:
        ctx.on_ready(_one_failure)


class _HookFails:
    """A hook added once its routes are live fails, so the failed fork stays plugged in, routes up and a cleanup owed.

    A hook added any earlier holds the routes back, and then a failure leaves none.
    """

    name = "hook-fails"
    inject = ("web",)

    def apply(self, ctx, config) -> None:
        app = ctx["web"].view(ctx)
        app.on_cleanup.append(_cleanup_hook)
        app.router.add_get("/fixture/slow", _slow)
        ctx.on_ready(lambda: app.on_startup.append(_startup_hook))


routes = _Routes()
quiet = _Quiet()
explodes = _Explodes()
fails_starting = _FailsStarting()
hook_fails = _HookFails()
