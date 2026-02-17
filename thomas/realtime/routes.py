from __future__ import annotations

from aiohttp import web
from pathlib import Path

from .config import load_realtime_config
from . import keys
from .ws_handler import handle_realtime_ws
from .uploads import store_upload


def _find_repo_root(start: Path) -> Path:
    """Walk upwards looking for a repo root that contains realtime static assets."""
    for p in [start] + list(start.parents):
        candidate_a = p / "web" / "static" / "realtime"
        candidate_b = p / "thomas" / "server" / "web" / "realtime"
        if candidate_a.exists() or candidate_b.exists():
            return p
    return start.parents[1] if len(start.parents) >= 2 else start


def setup_realtime_routes(app: web.Application):
    cfg = load_realtime_config()
    app[keys.CONFIG] = cfg

    here = Path(__file__).resolve()
    repo_root = _find_repo_root(here.parent)
    # Prefer Thomas' packaged web assets location, then legacy web/static path.
    static_dir = repo_root / "thomas" / "server" / "web" / "realtime"
    if not static_dir.exists():
        static_dir = repo_root / "web" / "static" / "realtime"

    if static_dir.exists():
        app.router.add_static("/static/realtime/", str(static_dir), show_index=False)

    async def realtime_page(request: web.Request):
        index = static_dir / "index.html"
        if not index.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(path=index)

    app.router.add_get("/realtime", realtime_page)

    # Websocket
    app.router.add_get("/api/realtime/ws", handle_realtime_ws)

    # Upload endpoint (multimodal files)
    async def upload(request: web.Request):
        cfg = app.get(keys.CONFIG) or app.get("realtime.config") or load_realtime_config()
        if not cfg.enabled:
            raise web.HTTPForbidden(text="realtime disabled")

        if request.content_length and request.content_length > cfg.max_upload_bytes:
            raise web.HTTPRequestEntityTooLarge(max_size=cfg.max_upload_bytes, actual_size=request.content_length)

        reader = await request.multipart()
        part = await reader.next()
        if part is None:
            raise web.HTTPBadRequest(text="no file")

        if part.name != "file":
            raise web.HTTPBadRequest(text="expected multipart field 'file'")

        filename = part.filename or "upload.bin"
        mime = part.headers.get("Content-Type", "application/octet-stream")

        data = await part.read(decode=False)
        if len(data) > cfg.max_upload_bytes:
            raise web.HTTPRequestEntityTooLarge(max_size=cfg.max_upload_bytes, actual_size=len(data))

        uploads_dir = Path(cfg.uploads_dir)
        info = store_upload(uploads_dir, filename=filename, mime=mime, data=data)

        # Return handle + metadata only (don’t leak absolute path)
        return web.json_response({
            "ok": True,
            "handle": info.handle,
            "name": info.name,
            "mime": info.mime,
            "size": info.size,
        })

    app.router.add_post("/api/realtime/upload", upload)
