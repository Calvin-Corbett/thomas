from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from aiohttp import web

from . import keys
from .config import load_realtime_config
from .uploads import store_upload
from .ws_handler import handle_realtime_ws

AccessChecker = Callable[[web.Request], None]


def _find_repo_root(start: Path) -> Path:
    """Walk upwards looking for a repo root that contains web/static/realtime."""
    for p in [start] + list(start.parents):
        candidate = p / "web" / "static" / "realtime"
        if candidate.exists():
            return p
    return start.parents[1] if len(start.parents) >= 2 else start


def setup_realtime_routes(app: web.Application, *, require_api_access: AccessChecker | None = None):
    cfg = load_realtime_config()
    app[keys.CONFIG] = cfg
    if require_api_access is not None:
        app[keys.REQUIRE_API_ACCESS] = require_api_access

    here = Path(__file__).resolve()
    repo_root = _find_repo_root(here.parent)
    static_dir = repo_root / "web" / "static" / "realtime"

    if static_dir.exists():
        app.router.add_static("/static/realtime/", str(static_dir), show_index=False)

    async def realtime_page(request: web.Request):
        index = static_dir / "index.html"
        if not index.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(path=index)

    app.router.add_get("/realtime", realtime_page)

    def _enforce_api_access(request: web.Request) -> None:
        checker = app.get(keys.REQUIRE_API_ACCESS) or app.get("realtime.require_api_access")
        if callable(checker):
            checker(request)

    # Websocket
    async def realtime_ws(request: web.Request):
        _enforce_api_access(request)
        return await handle_realtime_ws(request)

    app.router.add_get("/api/realtime/ws", realtime_ws)

    # Upload endpoint (multimodal files)
    async def upload(request: web.Request):
        _enforce_api_access(request)
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
        return web.json_response(
            {
                "ok": True,
                "handle": info.handle,
                "name": info.name,
                "mime": info.mime,
                "size": info.size,
            }
        )

    app.router.add_post("/api/realtime/upload", upload)
