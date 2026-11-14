"""The System Map's routes: the old page address, which leads to Agents, and the inventory it used to show.

``thomas.server.rows.system_map`` calls ``register_system_map_routes`` when the row turns on. The page itself is gone:
``/system-map`` sends you to the Agents workspace, and ``GET /api/system-map`` still serves the reading of what exists in
this project to other programs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web


def register_system_map_routes(app: Any, *, web_dir: Path, require_api_access: Callable[..., Any]) -> None:
    """Add ``/system-map``, ``/system-map/`` and ``GET /api/system-map`` to ``app``.

    ``web_dir`` is kept because the row passes it; no page is served from it any more.
    """
    del web_dir

    async def system_map_page(request: web.Request) -> web.StreamResponse:
        """The System Map page is gone: its old address leads to the Agents workspace, so saved links keep working."""
        raise web.HTTPFound("/agents?embed=1" if request.query.get("embed") == "1" else "/agents")

    async def api_system_map(request: web.Request) -> web.Response:
        """Return the inventory of what exists in this project.

        Every other check in this repo compares one change to the one before
        it. This one counts the SUM -- the branches, the separate working
        copies, the set-aside piles -- because that is the number that reached
        591 commits across 57 copies with nothing watching it.

        Like landing health, the git work is blocking, so it runs in a thread
        and never stalls the event loop. It reads only; nothing here prunes,
        drops or deletes.
        """
        require_api_access(request)
        from thomas.core.system_map import collect_system_map

        system_map = await asyncio.to_thread(collect_system_map)
        return web.json_response(system_map.as_dict())

    app.router.add_get("/system-map", system_map_page)
    app.router.add_get("/system-map/", system_map_page)
    app.router.add_get("/api/system-map", api_system_map)
