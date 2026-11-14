"""What your windows landed, as their record says, for ``GET /api/self/windows`` (spec 2026-10-12, section 8.4).

The promoter keeps each window's record in C:\\ProgramData\\ThomasWindow: one write-once file per event, which this
server's account may read and never write (scripts/cage/enable_window.ps1). This reads the opening and closing of each
window, newest first, with every change it landed or undid (Submission-Id, commit, files, lines), as the promoter read
them from dev when the window ended. A file that is not plain JSON is skipped, never fatal: this is a view of the
record, never its authority. The windows row (thomas/server/rows/windows.py) registers the route, behind the loopback
guard.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

RECORD_ROOT = Path(r"C:\ProgramData\ThomasWindow")
PATH = "/api/self/windows"
_NAME = re.compile(r"\d{8}-(window_opened|window_closed)\.json")
_LIMIT = 256 * 1024


def read_windows(root: Path = RECORD_ROOT, limit: int = 20) -> list[dict[str, Any]]:
    """The last *limit* windows, newest first: id, when opened, minutes, pairing code, why it ended, what it landed."""
    windows: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(root).glob("*.json")) if Path(root).is_dir() else []:
        if not _NAME.fullmatch(path.name) or path.stat().st_size > _LIMIT:
            continue
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(event, dict) or not isinstance(event.get("window_id"), str):
            continue
        row = windows.setdefault(event["window_id"], {"window_id": event["window_id"], "landed": []})
        if event.get("name") == "window_opened":
            for key in ("opened_at", "minutes", "ends", "pairing_code"):
                row[key] = event.get(key)
        elif event.get("name") == "window_closed":
            row["ended"] = event.get("reason")
            row["landed"] = event.get("landed") if isinstance(event.get("landed"), list) else []
    return list(reversed(list(windows.values())))[: max(0, limit)]


def register_window_routes(app: web.Application, *, require_loopback: Callable[[web.Request], None]) -> None:
    """What your windows landed: ``GET /api/self/windows`` (loopback only)."""

    async def windows(request: web.Request) -> web.Response:
        require_loopback(request)
        return web.json_response({"windows": read_windows()})

    app.router.add_get(PATH, windows)


__all__ = ["PATH", "RECORD_ROOT", "read_windows", "register_window_routes"]
