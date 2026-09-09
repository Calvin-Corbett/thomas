"""Watching a Code run: the live transcript feed and the state snapshot.

Split out of ``evolve_agent_routes`` because these two handlers are the only
ones that read a run without touching it. ``stream`` tails the transcript file
and re-frames it as SSE; ``status`` answers the same question for a client that
polls instead of listens. Neither starts, steers, approves or stops anything --
that is the launcher's half, and it stayed there.

They belong together because they answer the same question and must not drift
apart on it: which run are we talking about. Both accept an explicit ``run_id``
(or, for status, a ``conversation_id``), both fall back to the legacy
single-slot mirror when nothing is named, and both merge the per-conversation
registry with that mirror. A reader who fixes the resolution rule in one now
has the other in front of them.

``stream`` also carries the whole SSE mechanic -- the incremental line decoder,
the payload translation, the final "done" frame that only fires once the drain
has finished recording -- and nothing else in the Code surface uses any of it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil.forge_code_http_stream import IncrementalLineDecoder, line_to_sse_payload

from .evolve_agent_run_state import (
    APP_EVOLVE_AGENT_CONVO,
    APP_EVOLVE_AGENT_DRAIN,
    APP_EVOLVE_AGENT_PROJECT,
    APP_EVOLVE_AGENT_SESSION,
    APP_EVOLVE_AGENT_SETTINGS,
    APP_EVOLVE_AGENT_TASK,
    runs,
    slot_active,
    slot_for_run_id,
    slot_running,
)
from .evolve_agent_runtime import _await_recording, _recording_active, _recording_status, _sse_frame, _transcript_path


def build_evolve_agent_watch_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    catalog_root: Callable[[], Path],
    running: Callable[[], bool],
) -> dict[str, Any]:
    """Build the read-only run observers.

    ``running`` is the launcher's own answer for the legacy single-slot mirror,
    passed in so "is a run in flight" has one definition across the surface.
    """

    async def stream(request: web.Request) -> web.StreamResponse:
        require_api_access(request)
        session = dict(app.get(APP_EVOLVE_AGENT_SESSION) or {})
        run_id = str(session.get("run_id") or "legacy")
        recording = app.get(APP_EVOLVE_AGENT_DRAIN)
        wanted = str(request.query.get("run_id") or "").strip()
        if wanted and wanted != run_id:
            # Any REGISTERED run can be streamed, not just the most recent one.
            slot = slot_for_run_id(app, wanted)
            if slot is None:
                return web.json_response(
                    {"ok": False, "error": "that Code run is not active", "code": "run_not_active"}, status=409
                )
            session = dict(slot.get("session") or {})
            run_id = wanted
            recording = slot.get("drain")
        try:
            cursor = max(0, int(request.query.get("cursor") or 0))
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid stream cursor"}, status=400)
        transcript = Path(session.get("transcript") or _transcript_path(catalog_root()))
        proc = session.get("proc") or app.get(APP_EVOLVE_AGENT_TASK)
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await resp.prepare(request)
        pos = 0
        sequence = 0
        linedec = IncrementalLineDecoder()

        async def _emit_line(line: str) -> None:
            nonlocal sequence
            payload = line_to_sse_payload(line)
            if payload:
                sequence += 1
                if sequence > cursor:
                    await resp.write(_sse_frame(payload, run_id, sequence))

        try:
            while not (request.transport is None or request.transport.is_closing()):
                chunk = b""
                if transcript.exists():
                    with open(transcript, "rb") as fh:
                        fh.seek(pos)
                        chunk = fh.read()
                        pos = fh.tell()
                if chunk:
                    for line in linedec.feed(chunk):
                        await _emit_line(line)
                    # Data was flowing — loop again IMMEDIATELY (no poll delay) to
                    await asyncio.sleep(0)
                    continue
                if proc is None or proc.returncode is not None:
                    persistence = await _await_recording(recording)
                    # Final drain: the child may have flushed its last lines after
                    # our read above but before we noticed it exited — pick them up.
                    if transcript.exists():
                        with open(transcript, "rb") as fh:
                            fh.seek(pos)
                            tail = fh.read()
                            pos = fh.tell()
                        if tail:
                            for line in linedec.feed(tail):
                                await _emit_line(line)
                    for line in linedec.flush():
                        await _emit_line(line)
                    sequence += 1
                    if sequence > cursor:
                        await resp.write(
                            _sse_frame(
                                {
                                    "type": "done",
                                    **persistence,
                                    "conversation_id": session.get("conversation_id")
                                    or app.get(APP_EVOLVE_AGENT_CONVO)
                                    or "",
                                    "project_root": session.get("project_root")
                                    or app.get(APP_EVOLVE_AGENT_PROJECT)
                                    or "",
                                    "settings": session.get("settings") or app.get(APP_EVOLVE_AGENT_SETTINGS) or {},
                                },
                                run_id,
                                sequence,
                            )
                        )
                    break
                await asyncio.sleep(0.05)
        except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
            pass
        return resp

    def _status_payload(sess: dict[str, Any], drain: Any, *, is_running: bool) -> dict[str, Any]:
        return {
            "ok": True,
            "running": is_running,
            **_recording_status(drain),
            "run_id": sess.get("run_id") or "",
            "generation": sess.get("generation") or 0,
            "session": {
                "message": sess.get("message", ""),
                "started_at": sess.get("started_at"),
                "project_root": sess.get("project_root", ""),
                # Lets a reloaded page reattach to the running run's conversation.
                "conversation_id": sess.get("conversation_id", ""),
            },
            "settings": sess.get("settings") or app.get(APP_EVOLVE_AGENT_SETTINGS) or {},
        }

    async def status(request: web.Request) -> web.Response:
        require_api_access(request)
        # Per-slot resolution: ?conversation_id= or ?run_id= answers for THAT
        # run; default keeps the legacy most-recent shape plus a runs[] list.
        wanted_cid = str(request.query.get("conversation_id") or "").strip()
        wanted_run = str(request.query.get("run_id") or "").strip()
        if wanted_cid or wanted_run:
            slot = runs(app).get(wanted_cid) if wanted_cid else slot_for_run_id(app, wanted_run)
            sess = (slot or {}).get("session") or {}
            return web.json_response(_status_payload(sess, (slot or {}).get("drain"), is_running=slot_running(slot)))
        sess = app.get(APP_EVOLVE_AGENT_SESSION) or {}
        payload = _status_payload(sess, app.get(APP_EVOLVE_AGENT_DRAIN), is_running=running())
        payload["runs"] = [
            {
                "run_id": str((slot.get("session") or {}).get("run_id") or ""),
                "conversation_id": str((slot.get("session") or {}).get("conversation_id") or ""),
                "project_root": str((slot.get("session") or {}).get("project_root") or ""),
                "started_at": (slot.get("session") or {}).get("started_at"),
                "message": str((slot.get("session") or {}).get("message") or "")[:120],
                "running": slot_running(slot),
                "recording": _recording_active(slot.get("drain")),
            }
            for slot in runs(app).values()
            if slot_active(slot)
        ]
        return web.json_response(payload)

    return {
        "stream": stream,
        "status": status,
    }
