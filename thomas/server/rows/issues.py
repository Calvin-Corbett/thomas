"""The issue ledger routes, as a row: ``GET /api/issues`` and ``POST /api/issues``.

Off takes these two routes away and nothing else. The ledger is a file, ``runtime/logs/issues.jsonl``, that many parts of
Thomas append to directly, and the self review reads it directly, so all of that carries on whether the routes are
present or not. What stops is the web pages and other programs reporting a failure through the route, and asking for the
summary through it.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Issues:
    name = "issues"
    inject = ("web",)
    imports = ("thomas.server.routes.issues_aiohttp",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.issues_aiohttp import register_issue_routes

        register_issue_routes(ctx["web"].view(ctx))


plugin = _Issues()
