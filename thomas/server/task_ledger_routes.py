"""The task-ledger routes' registrar: the current and history views of a session's task, in both spellings.

``thomas.server.rows.task_ledger`` calls this when the row turns on. It lives beside ``app_routes_task_ledger.py``,
which still builds the handlers, and not inside it: that file stays loaded for the routes the server keeps, so a
registrar there could never be left unloaded on a server started with the row off.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from thomas.server.app_routes_task_ledger import build_task_ledger_handlers


def register_task_ledger_routes(app: Any, *, require_api_access: Callable[..., Any]) -> None:
    """Add the four task-ledger routes to ``app``, in the order the server's own table once held them."""
    handlers = build_task_ledger_handlers(app, require_api_access=require_api_access)
    current = handlers["api_task_ledger_current"]
    history = handlers["api_task_ledger_history"]
    app.router.add_get("/api/task_ledger/current", current)
    app.router.add_get("/api/task-ledger/current", current)
    app.router.add_get("/api/task_ledger/history", history)
    app.router.add_get("/api/task-ledger/history", history)
