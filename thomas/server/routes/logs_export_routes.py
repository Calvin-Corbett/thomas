"""``/api/logs/export``: the archive the settings page's Export logs button downloads.

settings.maintenance.js has probed this route with HEAD since the settings
script was split, and greys its button when the probe fails. Nothing served
the route, so the probe logged a 404 on every settings load and the button
was dead on every server. HEAD says whether this server has a logs directory at all; GET
packs the server log, its rotations and the chat logs into a zip, or a note
when nothing has been written yet. Only files
under the logs directory are ever packed.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

LOG_NAME_PREFIXES = ("thomas.log",)
CHAT_LOG_SUFFIXES = (".log", ".jsonl", ".txt")
MAX_ARCHIVE_INPUT_BYTES = 200 * 1024 * 1024


def _log_files(logs_dir: Path) -> list[Path]:
    root = Path(logs_dir)
    if not root.is_dir():
        return []
    found: list[Path] = []
    for entry in sorted(root.iterdir()):
        if entry.is_file() and entry.name.startswith(LOG_NAME_PREFIXES):
            found.append(entry)
    chat = root / "chat"
    if chat.is_dir():
        for entry in sorted(chat.rglob("*")):
            if entry.is_file() and entry.suffix.lower() in CHAT_LOG_SUFFIXES:
                found.append(entry)
    return found


def _archive(logs_dir: Path, files: list[Path]) -> bytes:
    buffer = io.BytesIO()
    packed = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if not files:
            # A server with a logs directory but nothing written yet is a working
            # server; the export says so instead of failing the probe.
            archive.writestr("README.txt", f"Thomas has no log files yet under {logs_dir}.\n")
        for path in files:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if packed + size > MAX_ARCHIVE_INPUT_BYTES:
                break
            try:
                # The live log may be held open by the server itself; read what is there.
                data = path.read_bytes()
            except OSError:
                continue
            archive.writestr(path.relative_to(logs_dir).as_posix(), data)
            packed += size
    return buffer.getvalue()


def setup_logs_export_routes(app: web.Application, *, logs_dir: Path | str, require_api_access=None) -> None:
    root = Path(logs_dir)

    def guard(request: web.Request) -> None:
        if require_api_access is not None:
            require_api_access(request)

    async def head(request: web.Request) -> web.Response:
        guard(request)
        if not root.is_dir():
            raise web.HTTPNotFound(text="this server has no logs directory")
        return web.Response(status=200, headers={"Content-Type": "application/zip"})

    async def get(request: web.Request) -> web.Response:
        guard(request)
        if not root.is_dir():
            raise web.HTTPNotFound(text="this server has no logs directory")
        files = _log_files(root)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        body = _archive(root, files)
        return web.Response(
            body=body,
            headers={
                "Content-Type": "application/zip",
                "Content-Disposition": f'attachment; filename="thomas-logs-{stamp}.zip"',
            },
        )

    # aiohttp derives HEAD from a GET by default; the probe must not build the archive.
    app.router.add_route("HEAD", "/api/logs/export", head)
    app.router.add_get("/api/logs/export", get, allow_head=False)


__all__ = ["setup_logs_export_routes"]
