"""Core aiohttp route registration for the web UI + JSON API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from aiohttp import web

_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("get", "/api/task-ledger/current", "api_task_ledger_current"),
    ("get", "/api/task-ledger/history", "api_task_ledger_history"),
    ("get", "/api/engines", "api_engines"),
    ("get", "/api/tools", "api_tools"),
    ("get", "/api/security/mutating-routes", "api_security_mutating_routes"),
    ("get", "/api/chats", "api_chats"),
    ("put", "/api/chats/{chat_id}", "api_chat_put"),
    ("delete", "/api/chats/{chat_id}", "api_chat_delete"),
)


def register_core_routes(
    app: web.Application,
    *,
    web_dir: Path,
    handlers: Mapping[str, Any],
) -> None:
    app.router.add_get("/", handlers["index"])
    if "settings" in handlers:
        app.router.add_get("/settings", handlers["settings"])
    if "companion" in handlers:
        app.router.add_get("/companion", handlers["companion"])
    app.router.add_static("/static/", web_dir, show_index=False)
    for method, path, handler_name in _ROUTES:
        handler = handlers[handler_name]
        getattr(app.router, f"add_{method}")(path, handler)
