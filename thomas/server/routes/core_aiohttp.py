"""Core aiohttp route registration for the web UI + JSON API."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
    if "landing" in handlers:
        app.router.add_get("/landing", handlers["landing"])
    app.router.add_static("/static/", web_dir, show_index=False)
    # Serve worker-built deliverables (generated games/apps) so the task card can
    # offer a one-click "Play" — loopback-only, path-traversal-safe.
    from thomas.server.routes.deliverable_aiohttp import register_deliverable_routes

    register_deliverable_routes(app)
    for method, path, handler_name in _ROUTES:
        handler = handlers[handler_name]
        getattr(app.router, f"add_{method}")(path, handler)

    # Add error handlers for 404 and 500
    async def handle_404(request: web.Request) -> web.StreamResponse:
        """Handle 404 Not Found errors."""
        error_path = web_dir / "error-404.html"
        if error_path.exists():
            try:
                html = error_path.read_text(encoding="utf-8", errors="replace")
                return web.Response(
                    text=html,
                    status=404,
                    content_type="text/html",
                )
            except (OSError, UnicodeDecodeError):
                pass
        return web.Response(
            text="404 Not Found",
            status=404,
            content_type="text/plain",
        )

    async def handle_500(request: web.Request) -> web.StreamResponse:
        """Handle 500 Internal Server Error."""
        error_path = web_dir / "error-500.html"
        if error_path.exists():
            try:
                html = error_path.read_text(encoding="utf-8", errors="replace")
                return web.Response(
                    text=html,
                    status=500,
                    content_type="text/html",
                )
            except (OSError, UnicodeDecodeError):
                pass
        return web.Response(
            text="500 Internal Server Error",
            status=500,
            content_type="text/plain",
        )

    # Register error handlers as middleware
    @web.middleware
    async def error_middleware(request: web.Request, handler):  # type: ignore[no-untyped-def]
        try:
            return await handler(request)
        except web.HTTPNotFound:
            path = str(request.path or "")
            if path.startswith(("/api/", "/gateway/", "/v1/")):
                raise
            return await handle_404(request)
        except web.HTTPException:
            raise
        except web.HTTPServerError:
            return await handle_500(request)
        except Exception:
            return await handle_500(request)

    # Insert error middleware at the beginning for proper error handling
    app.middlewares.insert(0, error_middleware)
