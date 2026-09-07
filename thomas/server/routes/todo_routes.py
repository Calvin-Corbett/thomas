"""HTTP surface for the model's checklist (the ``todo.write`` tool).

GET /api/chat/todos -> {"todos": [record, ...]} newest first; a record is
{session_id, title, items: [{text, status}], updated_at}. The chat page polls
this and draws the plan under the reply. Registered from parity_routes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.core.todo_book import TodoBook, todo_book


def setup_todo_routes(
    app: web.Application,
    *,
    book: TodoBook | None = None,
    require_api_access: Callable[[web.Request], Any] | None = None,
) -> None:
    active = book or todo_book()
    guard = require_api_access or (lambda _request: None)

    async def list_todos(request: web.Request) -> web.Response:
        guard(request)
        # One chat's list with a session id; only the session-less (headless)
        # list without one. Never every chat's lists at once.
        session_id = str(request.query.get("session_id") or "").strip()
        record = active.get(session_id)
        return web.json_response({"todos": [record] if record else []})

    app.router.add_get("/api/chat/todos", list_todos)


__all__ = ["setup_todo_routes"]
