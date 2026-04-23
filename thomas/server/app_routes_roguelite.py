"""Roguelite marketplace routes."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from aiohttp import web


def register_roguelite_routes(app: web.Application) -> None:
    static_root = Path(__file__).resolve().parent.parent / "marketplace" / "roguelike" / "static"

    async def _roguelite_menu(_request: web.Request) -> web.StreamResponse:
        menu_path = static_root / "menu.html"
        if menu_path.is_file():
            return web.Response(
                text=menu_path.read_text(encoding="utf-8", errors="replace"),
                content_type="text/html",
            )
        raise web.HTTPNotFound()

    async def _roguelite_play(_request: web.Request) -> web.StreamResponse:
        game_path = static_root / "roguelike.html"
        if game_path.is_file():
            return web.Response(
                text=game_path.read_text(encoding="utf-8", errors="replace"),
                content_type="text/html",
            )
        raise web.HTTPNotFound()

    async def _roguelite_asset(request: web.Request) -> web.StreamResponse:
        raw = str(request.match_info.get("path", "") or "").replace("\\", "/").lstrip("/")
        rel = Path(raw)
        if not raw or rel.is_absolute() or ".." in rel.parts:
            raise web.HTTPNotFound()
        candidate = static_root / rel
        if candidate.is_file():
            resp = web.FileResponse(candidate)
            guessed, _ = mimetypes.guess_type(str(candidate))
            if guessed:
                resp.content_type = guessed
            return resp
        raise web.HTTPNotFound()

    app.router.add_get("/roguelike", _roguelite_menu)
    app.router.add_get("/roguelike/", _roguelite_menu)
    app.router.add_get("/roguelite", _roguelite_menu)
    app.router.add_get("/roguelite/", _roguelite_menu)
    app.router.add_get("/roguelike/play", _roguelite_play)
    app.router.add_get("/roguelite/play", _roguelite_play)
    app.router.add_get("/roguelike/assets/{path:.*}", _roguelite_asset)
    app.router.add_get("/roguelite/assets/{path:.*}", _roguelite_asset)
