"""Rows to run the real proof on, as if they had shipped. A row is read for what it reaches, so these have a file alone.

No shipped row has a startup hook yet, and the first will not be built with this proof free to change.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web


async def _a_moment(_app: Any) -> None:
    await asyncio.sleep(0.05)


async def _answers(_request: web.Request) -> web.Response:
    return web.Response(text="answered")


class _Hooked:
    inject = ("web",)

    def __init__(self, name: str, *routes: tuple[str, str]) -> None:
        self.name = name
        self._routes = routes

    def apply(self, ctx: Any, config: Any) -> None:
        view = ctx["web"].view(ctx)
        view.on_startup.append(_a_moment)
        for method, path in self._routes:
            view.router.add_route(method, path, _answers)


class _FailsToLoad:
    name = "fails-to-load"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        raise OSError("this row can never load")


well_behaved = _Hooked("well-behaved", ("GET", "/well-behaved"))
takes_the_off_switch = _Hooked("takes-the-off-switch", ("POST", "/api/plugins/{any}/{id}/off"))
fails_to_load = _FailsToLoad()
