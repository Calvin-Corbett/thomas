"""``GET /api/contributors``: how many commits on this copy Thomas, Claude, Codex and you each made.

``thomas.server.rows.contributors`` calls ``register_contributors_routes`` when the row turns on. The counting is
``thomas.core.contributors``, which only reads the history.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core import contributors

# thomas/server/routes/contributors.py: the checkout is three folders up.
_THIS_COPY = Path(__file__).resolve().parents[3]


def register_contributors_routes(app: Any, *, require_api_access: Callable[..., Any], repo: Path | None = None) -> None:
    """Add ``GET /api/contributors`` to ``app``. ``repo`` is the copy to count, this one when it is left out."""
    where = _THIS_COPY if repo is None else repo

    async def api_contributors(request: web.Request) -> web.Response:
        require_api_access(request)
        # git is a process of its own and a long history takes a moment, so the loop is not held while it runs.
        found = await asyncio.to_thread(contributors.tally, where)
        return web.json_response(found.as_dict(), headers={"Cache-Control": "no-store"})

    app.router.add_get("/api/contributors", api_contributors)
