"""Helper builders for app_middleware_handlers.

Extracted from ``thomas.server.app_middleware_handlers`` to keep that module
under the architecture size limit. These builders return the static HTML page
handlers (index / classic / settings / companion) used by the web app. They are
plain factories so behavior is identical to the previous inline closures.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thomas import __version__ as THOMAS_VERSION


def build_page_handlers(
    web_dir: Path,
    web_build_fingerprint: Callable[..., str],
) -> dict[str, Callable[[Any], Any]]:
    """Build the static HTML page handlers for the web app.

    Returns a mapping of handler name -> coroutine handler. Each handler renders
    the corresponding ``*.html`` file, substituting the Thomas version and a
    cache-busting web-build fingerprint, and falls back to a raw FileResponse on
    read errors.
    """
    from aiohttp import web

    async def index(request: web.Request) -> web.StreamResponse:
        # The chat UI is now the "Thomas Chat" design (chat.html). The legacy SPA
        # (index.html) still hosts every workspace and is served at /classic; the
        # new sidebar deep-links into it.
        try:
            html = await asyncio.to_thread(
                lambda: (web_dir / "chat.html").read_text(encoding="utf-8", errors="replace")
            )
            web_build = web_build_fingerprint("chat.html", "js/workspace_shell.js")
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            html = html.replace("__THOMAS_WEB_BUILD__", web_build)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(web_dir / "chat.html")

    async def classic(request: web.Request) -> web.StreamResponse:
        # Legacy full SPA — workspace host. Reached from the new chat UI's sidebar
        # (deep-linked via ?nav=<mode>).
        try:
            html = await asyncio.to_thread(
                lambda: (web_dir / "index.html").read_text(encoding="utf-8", errors="replace")
            )
            web_build = web_build_fingerprint(
                "js/app.js",
                "js/app_runtime_loader.js",
                "js/runtime/001_preamble.js",
                "js/runtime/canvas_workspace_contract.js",
                "js/runtime/canvas_workspace_runtime.js",
                "js/runtime/048_ui_studio_canvas.js",
                "js/workspace_shell.js",
                "js/ui_edit_layout.js",
                "js/ui_edit_mode.js",
                "css/workspace_shell.css",
                "css/virtual_office_workspace.css",
                "css/ui_edit_mode.css",
                "index.html",
            )
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            html = html.replace("__THOMAS_WEB_BUILD__", web_build)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(web_dir / "index.html")

    async def settings(request: web.Request) -> web.StreamResponse:
        try:
            html = (web_dir / "settings.html").read_text(encoding="utf-8", errors="replace")
            web_build = web_build_fingerprint(
                "settings.html",
                "settings.style01.css",
                "settings.script01.js",
                "js/workspace_shell.js",
                "js/ui_edit_layout.js",
                "js/ui_edit_mode.js",
                "css/workspace_shell.css",
                "css/ui_edit_mode.css",
            )
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            html = html.replace("__THOMAS_WEB_BUILD__", web_build)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(web_dir / "settings.html")

    async def companion(request: web.Request) -> web.StreamResponse:
        try:
            html = (web_dir / "companion.html").read_text(encoding="utf-8", errors="replace")
            web_build = web_build_fingerprint(
                "js/app.js",
                "js/app_runtime_loader.js",
                "js/runtime/001_preamble.js",
                "index.html",
            )
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            html = html.replace("__THOMAS_WEB_BUILD__", web_build)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(web_dir / "companion.html")

    return {
        "index": index,
        "classic": classic,
        "settings": settings,
        "companion": companion,
    }
