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

# The self-contained chat modules the chat page handler injects (frontier
# parity, 2026-09-05): question panel, "/" palette, reply feedback, cost
# readout, fast-mode pill, checklist. Each tag is stamped from the module's
# own bytes: the page's build fingerprint hashes chat.html and
# workspace_shell.js only, so a browser kept old copies of these after they
# changed on disk (found on the verify server the same day).
_CHAT_MODULES = (
    "chat_session_id",  # first: the panels ask it which chat is open
    "rate_limit_banner",
    "ask_user_panel",
    "slash_palette",
    "message_feedback",
    "cost_readout",
    "fast_mode",
    "todo_panel",
)
_SETTINGS_MODULES = ("settings_parity",)


def _module_stamp(web_dir: Path, module: str) -> str:
    """A short stamp of the module file's bytes; the page build stamp when it is unreadable."""
    import hashlib

    try:
        return hashlib.sha1((web_dir / "js" / f"{module}.js").read_bytes()).hexdigest()[:12]  # noqa: S324
    except OSError:
        return "__THOMAS_WEB_BUILD__"


def _module_tag(web_dir: Path, module: str) -> str:
    return f'<script src="/static/js/{module}.js?v={_module_stamp(web_dir, module)}"></script>'


def _inject_modules(html: str, modules: tuple[str, ...], web_dir: Path | None) -> str:
    if "</body>" not in html:
        return html
    root = web_dir or _web_dir()
    missing = "".join(_module_tag(root, m) for m in modules if f"/static/js/{m}.js?" not in html)
    if not missing:
        return html
    # The LAST closing body tag: chat.html carries the string "</body>" inside
    # an inline script (a template), and splicing there broke the page.
    head, _sep, tail = html.rpartition("</body>")
    return f"{head}{missing}</body>{tail}"


def _web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def inject_ask_user_panel(html: str, *, web_dir: Path | None = None) -> str:
    """Attach the self-contained chat modules to the chat page, once each, before the closing body tag."""
    return _inject_modules(html, _CHAT_MODULES, web_dir)


def inject_settings_parity(html: str, *, web_dir: Path | None = None) -> str:
    """Attach the run-time settings cards (sensitive sites, reply speed, scheduled tasks).

    settings.html is over the size guard's hard limit, so the cards are
    inserted by a script rather than written into the markup.
    """
    return _inject_modules(html, _SETTINGS_MODULES, web_dir)


def inject_overlay(html: str, stamp_token: str) -> str:
    """Splice the user overlay into a served page; a broken overlay never takes the page down.

    thomas/server/overlay/render.py puts the overlay stylesheet, its JSON view
    and one runtime tag before </head>. The stamp token is the placeholder the
    calling handler rewrites next, so the runtime tag is cache-busted with it.
    """
    try:
        from thomas.server.overlay.render import inject

        return inject(html, stamp_token)
    except (OSError, ValueError, RuntimeError) as exc:
        import logging

        logging.getLogger(__name__).warning("overlay injection skipped: %s", exc)
        return html


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
            html = inject_overlay(html, "__THOMAS_WEB_BUILD__")
            html = inject_ask_user_panel(html)
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
            html = inject_overlay(html, "__THOMAS_WEB_BUILD__")
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
            html = inject_overlay(html, "__THOMAS_WEB_BUILD__")
            html = inject_settings_parity(html)
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
            html = inject_overlay(html, "__THOMAS_WEB_BUILD__")
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
