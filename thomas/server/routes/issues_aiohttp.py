"""The issue ledger routes: ``GET /api/issues`` and ``POST /api/issues``.

GET answers with the failure summary for the last ``hours`` (one hour to two weeks, 24 when missing or not a number).
POST appends one client-side failure to the ledger. The ledger itself is ``thomas/server/issue_ledger.py``, which
many other modules write to directly, so it is imported inside each handler and not here.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web


def register_issue_routes(app: Any) -> None:
    """Register the two routes on ``app``. Neither handler asks the access guard, as they did in the shell."""

    # Issue ledger: "watch it like a report" — GET the failure summary, POST a
    # client-side (UI) failure. See thomas/server/issue_ledger.py.
    async def api_issues(request: web.Request) -> web.Response:
        from thomas.server.issue_ledger import summarize

        try:
            hours = max(1, min(24 * 14, int(request.query.get("hours", "24"))))
        except (TypeError, ValueError):
            hours = 24
        return web.json_response({"ok": True, **summarize(hours=hours)})

    async def api_issues_report(request: web.Request) -> web.Response:
        from thomas.server.issue_ledger import record_issue

        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        record_issue(
            surface=str((body or {}).get("surface") or "ui"),
            kind=str((body or {}).get("kind") or "client_error"),
            message=str((body or {}).get("message") or ""),
            context=body.get("context") if isinstance((body or {}).get("context"), dict) else {},
        )
        return web.json_response({"ok": True})

    app.router.add_get("/api/issues", api_issues)
    app.router.add_post("/api/issues", api_issues_report)
