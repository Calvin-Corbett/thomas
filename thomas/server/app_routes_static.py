"""Static asset helpers for Thomas server routes."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from aiohttp import web


async def static_compat_response(request: web.Request, web_dir: Path) -> web.StreamResponse:
    """Serve both modern shell assets and legacy module files under /static/."""
    raw_path = str(request.match_info.get("path", "") or "").replace("\\", "/").lstrip("/")
    rel_path = Path(raw_path)
    if not raw_path or rel_path.is_absolute() or ".." in rel_path.parts:
        raise web.HTTPNotFound()

    candidates = (
        web_dir / rel_path,
        web_dir / "static" / rel_path,
    )
    for candidate in candidates:
        if candidate.is_file():
            response = web.FileResponse(candidate)
            guessed_type, _ = mimetypes.guess_type(str(candidate))
            if guessed_type:
                response.content_type = guessed_type
            return response
    raise web.HTTPNotFound()
