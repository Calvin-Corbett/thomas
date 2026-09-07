"""The overlay's HTTP surface: read the view, read the manifest, append records.

Registered from app_core.py beside the realtime mount (app_routes_init.py is
over its size limit and is not touched). All three routes sit behind the same
API-access guard as /api/ui/redesign. The POST is the ONLY path by which the
base ever writes the overlay, and it only runs on an explicit user action
(Redesign's Apply, a theme edit, a rename); see docs/OVERLAY.md.

Honesty at the edge, with a stable ``code`` on every refusal: the body is
read with a byte ceiling on what is actually read (a chunked body has no
Content-Length to trust); ``overlay_id`` is a strict precondition (null only
while no overlay exists, the exact id once one does; anything else writes
nothing); a broken manifest is a 500 that names the file; a crossed limit,
a stale id, a held lock and a link inside the boundary each refuse with
nothing written. Rejected records travel back with their reasons next to the
accepted ones, so the browser can say exactly what landed and what did not.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable

from aiohttp import web

from thomas.server.overlay import manifest as m
from thomas.server.overlay import paths, render
from thomas.server.overlay.records import birth_base

log = logging.getLogger(__name__)

MAX_RECORDS = 200
MAX_BODY_BYTES = 512 * 1024


class _Refused(Exception):
    def __init__(self, status: int, code: str, error: str) -> None:
        super().__init__(error)
        self.status, self.code, self.error = status, code, error


def _no_store(payload: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, headers={"Cache-Control": "no-store"})


def _refusal(status: int, code: str, error: str) -> web.Response:
    return _no_store({"ok": False, "code": code, "error": error}, status)


async def _denied(require_api_access: Callable[[web.Request], Any], request: web.Request) -> web.StreamResponse | None:
    """Run the guard, whether it raises, returns a response, or returns nothing."""
    outcome = require_api_access(request)
    if inspect.isawaitable(outcome):
        outcome = await outcome
    return outcome if isinstance(outcome, web.StreamResponse) else None


async def _read_body(request: web.Request) -> dict[str, Any]:
    """The JSON body, refused by the bytes actually read, never by a header that may be absent."""
    if (request.content_length or 0) > MAX_BODY_BYTES:
        raise _Refused(413, "too_large", f"body larger than {MAX_BODY_BYTES} bytes")
    chunks: list[bytes] = []
    size = 0
    while True:  # read() returns whatever chunk is ready, so count until the ceiling or the end
        chunk = await request.content.read(65536)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise _Refused(413, "too_large", f"body larger than {MAX_BODY_BYTES} bytes")
    raw = b"".join(chunks)
    try:
        body = m.parse_json(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _Refused(400, "bad_body", f"body must be strict UTF-8 JSON ({exc})") from exc
    if not isinstance(body, dict) or not isinstance(body.get("records"), list) or not isinstance(body.get("action"), dict):
        raise _Refused(400, "bad_body", "body needs action (object) and records (list)")
    extra = sorted(set(body) - {"overlay_id", "action", "records"})
    if extra:
        raise _Refused(400, "bad_body", f"body has fields this route does not read: {', '.join(extra)}")
    if len(body["records"]) > MAX_RECORDS:
        raise _Refused(400, "bad_body", f"at most {MAX_RECORDS} records per write")
    if "overlay_id" not in body or not isinstance(body["overlay_id"], (str, type(None))):
        raise _Refused(400, "bad_body", "overlay_id must be present: null while no overlay exists, else its exact id")
    return body


def _with_css(view: dict[str, Any]) -> dict[str, Any]:
    css, published = render.rendered(view)
    return {"view": published, "css": css}


def setup_overlay_routes(app: web.Application, *, require_api_access: Callable[[web.Request], Any]) -> None:
    async def view(request: web.Request) -> web.StreamResponse:
        if denied := await _denied(require_api_access, request):
            return denied
        return _no_store({"ok": True, **_with_css(render.current_view())})

    async def manifest_view(request: web.Request) -> web.StreamResponse:
        if denied := await _denied(require_api_access, request):
            return denied
        path = paths.manifest_path()
        try:
            loaded = await asyncio.to_thread(m.load, path)
        except m.ManifestBroken as exc:
            return _refusal(500, "overlay_broken", str(exc))
        if loaded is None:
            return _no_store({"ok": True, "present": False, "path": str(path)})
        return _no_store({"ok": True, "present": True, "version": m.SCHEMA, "overlay": loaded.header,
                          "records": list(loaded.records)})

    async def records(request: web.Request) -> web.StreamResponse:
        if denied := await _denied(require_api_access, request):
            return denied
        try:
            body = await _read_body(request)
        except _Refused as refused:
            return _refusal(refused.status, refused.code, refused.error)
        expected = body["overlay_id"]  # exactly as sent: only a literal null means "no overlay yet"
        try:
            # Off the event loop: the write takes a lock with bounded sleeps and does disk I/O.
            result = await asyncio.to_thread(
                lambda: m.append(body["records"], body["action"], birth_base(), expected_overlay_id=expected)
            )
        except m.ActionInvalid as exc:
            return _refusal(400, "bad_body", f"action: {exc}")
        except m.OverlayMismatch as exc:
            return _refusal(409, "overlay_mismatch", str(exc))
        except m.OverlayLimit as exc:
            return _refusal(409, "overlay_limit", str(exc))
        except m.OverlayIncoherent as exc:
            return _refusal(409, "overlay_incoherent", str(exc))
        except m.OverlayLocked as exc:
            return _refusal(503, "overlay_locked", str(exc))
        except m.OverlayWriteFailed as exc:
            log.warning("overlay write failed: %s", exc)
            return _refusal(500, "overlay_write_failed", str(exc))
        except m.ManifestBroken as exc:
            log.warning("overlay write refused: %s", exc)
            return _refusal(500, "overlay_broken", str(exc))
        except m.OverlayUnsafe as exc:
            log.warning("overlay write refused: %s", exc)
            return _refusal(500, "overlay_unsafe", str(exc))
        render.invalidate()
        return _no_store({
            "ok": True, "created": result.created, "rev": result.rev, "overlay_id": result.overlay_id,
            "accepted": result.accepted, "rejected": result.rejected, **_with_css(render.current_view()),
        })

    app.router.add_get("/api/ui/overlay", view)
    app.router.add_get("/api/ui/overlay/manifest", manifest_view)
    app.router.add_post("/api/ui/overlay/records", records)
