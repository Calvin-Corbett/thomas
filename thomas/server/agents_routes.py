"""The System workspace's routes: its page and the machine-vitals history it charts.

The row and its address were named Agents first. The old page is gone (2026-11-09); ``/agents`` still answers, with
the System page, so saved links and the three older addresses that redirect there keep working.

``thomas.server.rows.agents`` calls ``register_agents_routes`` when the row turns on. The task board itself reads
``/api/mission/control``, which the work row owns, so this row adds only the page and the vitals.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web


def register_agents_routes(app: Any, *, web_dir: Path, require_api_access: Callable[..., Any], history: Any) -> None:
    """Add ``/agents``, ``/system`` (each with a trailing-slash twin) and ``GET /api/agents/vitals`` to ``app``."""

    async def api_agents_vitals(request: web.Request) -> web.Response:
        require_api_access(request)
        return web.json_response(history.snapshot())

    async def system_page(request: web.Request) -> web.StreamResponse:
        """The System page: what Thomas is doing and how he is, a page at a time (2026-11-09)."""
        _ = request
        page = (web_dir / "system.html").resolve()
        if not page.is_relative_to(web_dir.resolve()) or not page.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(page, headers={"Cache-Control": "no-store"})

    app.router.add_get("/system", system_page)
    app.router.add_get("/system/", system_page)
    app.router.add_get("/agents", system_page)
    app.router.add_get("/agents/", system_page)
    app.router.add_get("/api/agents/vitals", api_agents_vitals)
