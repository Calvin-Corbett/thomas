"""Serve worker-built deliverables (e.g. a generated game) as a playable app.

The provider-native worker builds user deliverables in an ISOLATED workspace at
``~/.thomas/workspaces/<execution_id>/`` (never the source repo). The build works,
but the finished artifact was never served — so a "build me a game" result was a
file the user couldn't actually open. This module serves that workspace, loopback-
only and path-traversal-safe, so the task card can link a one-click "Play".

Route: GET /deliverable/{execution_id}            -> the workspace entry file
       GET /deliverable/{execution_id}/{tail:.*}  -> a specific file under it
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

from aiohttp import web

# Must match thomas/server/chat_delegation.py::_ensure_task_workspace.
_WORKSPACES_BASE = Path.home() / ".thomas" / "workspaces"
_ENTRY_PREFERENCES = ("index.html", "game.html", "main.html")


def _safe_id(execution_id: str) -> str:
    """Same sanitization _ensure_task_workspace uses to name the dir."""
    return "".join(ch for ch in str(execution_id or "") if ch.isalnum() or ch in "-_")


def _workspace_dir(execution_id: str) -> Path | None:
    safe = _safe_id(execution_id)
    if not safe:
        return None
    base = _WORKSPACES_BASE.resolve()
    target = (base / safe).resolve()
    # Containment guard: target must be directly under the workspaces base.
    if target.parent != base or not target.is_dir():
        return None
    return target


def deliverable_entry(execution_id: str) -> str | None:
    """Return the relative entry filename for a workspace, or None if no web artifact."""
    wd = _workspace_dir(execution_id)
    if wd is None:
        return None
    htmls = sorted(p for p in wd.rglob("*.html") if p.is_file())
    if not htmls:
        return None
    # Prefer a top-level index.html / game.html; else the shallowest, then first.
    for name in _ENTRY_PREFERENCES:
        cand = wd / name
        if cand.is_file():
            return name
    htmls.sort(key=lambda p: (len(p.relative_to(wd).parts), str(p.relative_to(wd))))
    return str(htmls[0].relative_to(wd)).replace("\\", "/")


def deliverable_url(execution_id: str) -> str:
    """Public URL for the workspace entry, or "" if there's nothing playable."""
    entry = deliverable_entry(execution_id)
    if not entry:
        return ""
    return f"/deliverable/{_safe_id(execution_id)}/{entry}"


def _is_loopback(request: web.Request) -> bool:
    peer = request.transport.get_extra_info("peername") if request.transport else None
    host = peer[0] if isinstance(peer, tuple) and peer else ""
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def handle_deliverable(request: web.Request) -> web.StreamResponse:
    # Worker output is untrusted generated content; only ever serve it to the local UI.
    if not _is_loopback(request):
        raise web.HTTPForbidden(text="Deliverables are served on loopback only.")
    execution_id = request.match_info.get("execution_id", "")
    wd = _workspace_dir(execution_id)
    if wd is None:
        raise web.HTTPNotFound(text="No deliverable for this task.")
    tail = request.match_info.get("tail", "") or (deliverable_entry(execution_id) or "")
    if not tail:
        raise web.HTTPNotFound(text="No playable file in this deliverable.")
    target = (wd / tail).resolve()
    # Path-traversal guard: resolved file must stay inside the workspace dir.
    if not (target == wd or wd in target.parents) or not target.is_file():
        raise web.HTTPNotFound(text="File not found in deliverable.")
    return web.FileResponse(target)


def register_deliverable_routes(app: web.Application) -> None:
    app.router.add_get("/deliverable/{execution_id}", handle_deliverable)
    app.router.add_get("/deliverable/{execution_id}/{tail:.*}", handle_deliverable)
