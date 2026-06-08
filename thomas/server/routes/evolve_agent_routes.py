"""HTTP API for the *directed* Evolve agent -- Thomas's self-builder.

This is the direct engineering seam. The Evolve chat talks straight to the
Evolve agent (Thomas's own autonomy-4 agent loop), bypassing the normal
``chat -> dispatcher -> task-manager`` route: self-development is not a task to
hand off, it is a direct engineering session.

In *directed* mode the agent runs against the LIVE repo and edits it directly --
git + the existing gates are the safety net and the user is in the loop watching
the stream. Its work (reasoning, tool calls, edits) is streamed back over SSE so
the user can see it and steer it -- the Codex/Claude-Code engineering experience,
powered entirely by Thomas's own model (no external CLIs).

Autonomous mode stays in the existing green/blue loop (``evolve_loop_routes``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)

APP_EVOLVE_AGENT_TASK = "evolve_agent_task"
APP_EVOLVE_AGENT_DRAIN = "evolve_agent_drain"
APP_EVOLVE_AGENT_SESSION = "evolve_agent_session"


def _default_repo_root() -> Path:
    # thomas/server/routes/evolve_agent_routes.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def _agent_dir(root: Path) -> Path:
    d = root / ".thomas" / "evolve" / "agent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _transcript_path(root: Path) -> Path:
    return _agent_dir(root) / "transcript.txt"


async def _drain(proc: Any, transcript: Path) -> None:
    """Stream the agent's combined stdout into the transcript file, line by line,
    flushing so the SSE tail sees output as it happens."""
    try:
        with open(transcript, "ab") as fh:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                fh.write(line)
                fh.flush()
    except Exception:  # noqa: BLE001 - draining is best-effort; never crash the server
        log.warning("evolve agent: transcript drain failed", exc_info=True)
    finally:
        with contextlib.suppress(Exception):
            await proc.wait()


def build_evolve_agent_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> dict[str, Any]:
    def _root() -> Path:
        return Path(root_resolver())

    def _running() -> bool:
        proc = app.get(APP_EVOLVE_AGENT_TASK)
        return proc is not None and proc.returncode is None

    async def send(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        message = str((body or {}).get("message") or "").strip()
        if not message:
            return web.json_response({"ok": False, "error": "empty message"}, status=400)
        if _running():
            return web.json_response({"ok": False, "error": "agent is already working"}, status=409)

        root = _root()
        transcript = _transcript_path(root)
        transcript.write_bytes(b"")  # fresh transcript for this turn; the stream tails it (append)
        # Directed mode: run Thomas's OWN agent loop on the LIVE repo (direct
        # edits). autonomy 4 = the full engineering agent; git is the safety net.
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "thomas",
            "chat",
            "--autonomy-level",
            "4",
            message,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_DRAIN] = asyncio.ensure_future(_drain(proc, transcript))
        app[APP_EVOLVE_AGENT_SESSION] = {"started_at": time.time(), "message": message}
        return web.json_response({"ok": True, "started": True})

    async def stream(request: web.Request) -> web.StreamResponse:
        require_api_access(request)
        transcript = _transcript_path(_root())
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
        try:
            while not (request.transport is None or request.transport.is_closing()):
                chunk = b""
                if transcript.exists():
                    with open(transcript, "rb") as fh:
                        fh.seek(pos)
                        chunk = fh.read()
                        pos = fh.tell()
                if chunk:
                    text = chunk.decode("utf-8", errors="replace")
                    await resp.write(("data: " + json.dumps({"type": "output", "text": text}) + "\n\n").encode("utf-8"))
                if not _running():
                    proc = app.get(APP_EVOLVE_AGENT_TASK)
                    rc = proc.returncode if proc is not None else None
                    await resp.write(
                        ("data: " + json.dumps({"type": "done", "returncode": rc}) + "\n\n").encode("utf-8")
                    )
                    break
                await asyncio.sleep(0.4)
        except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
            pass
        return resp

    async def status(request: web.Request) -> web.Response:
        require_api_access(request)
        sess = app.get(APP_EVOLVE_AGENT_SESSION) or {}
        return web.json_response(
            {
                "ok": True,
                "running": _running(),
                "session": {"message": sess.get("message", ""), "started_at": sess.get("started_at")},
            }
        )

    async def stop(request: web.Request) -> web.Response:
        require_api_access(request)
        proc = app.get(APP_EVOLVE_AGENT_TASK)
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
        return web.json_response({"ok": True, "stopped": True})

    return {"send": send, "stream": stream, "status": status, "stop": stop}


def register_evolve_agent_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> None:
    """Register the directed Evolve-agent API onto the aiohttp app."""
    handlers = build_evolve_agent_handlers(app, require_api_access=require_api_access, root_resolver=root_resolver)
    app.router.add_post("/api/evolve/agent/send", handlers["send"])
    app.router.add_get("/api/evolve/agent/stream", handlers["stream"])
    app.router.add_get("/api/evolve/agent/status", handlers["status"])
    app.router.add_post("/api/evolve/agent/stop", handlers["stop"])
