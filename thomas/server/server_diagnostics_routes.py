"""The server-diagnostics routes' registrar: the engines list, the tools list and the landing heartbeat.

``thomas.server.rows.server_diagnostics`` calls this when the row turns on. The handlers are built by
``app_routes_task_ledger.py``, which stays loaded for the security snapshot route the server keeps, so the registrar lives
in a file of its own and can be left unloaded on a server started with the row off.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from thomas.server.app_routes_task_ledger import build_task_ledger_handlers


def register_server_diagnostics_routes(app: Any, *, require_api_access: Callable[..., Any]) -> None:
    """Add ``GET /api/landing-health``, ``GET /api/engines`` and ``GET /api/tools`` to ``app``."""
    handlers = build_task_ledger_handlers(app, require_api_access=require_api_access)
    app.router.add_get("/api/landing-health", handlers["api_landing_health"])
    app.router.add_get("/api/engines", handlers["api_engines"])
    app.router.add_get("/api/tools", handlers["api_tools"])
