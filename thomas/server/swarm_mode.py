"""
aiohttp integration for Swarm Mode.

This module is intentionally small and dependency-free. It provides:
- POST /api/chat integration handler for mode="swarm"
- POST /api/runs/{run_id}/cancel endpoint (localhost-only)

Because Thomas' internal wiring may differ per repo version, this module exposes
a couple of hooks so app.py can pass in the existing tool executor and agent
implementations without invasive refactors.

Expected integration pattern (pseudo):

from thomas.server.swarm_mode import handle_swarm_chat, handle_cancel

async def chat_handler(request):
    payload = await request.json()
    if payload.get("mode") == "swarm":
        return await handle_swarm_chat(
            request,
            payload=payload,
            user_request=payload["message"],
            run_id=run_id,
            session_id=session_id,
            subagents=subagents,     # planner/coder/tester/reviewer objects
            tool_call=tool_call,     # async (name,args) -> dict result
            tool_mutates_fs=tool_mutates_fs,  # optional (name,args)->bool
        )
    ...

app.router.add_post("/api/runs/{run_id}/cancel", handle_cancel)
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, Awaitable, Callable, Dict, Optional

from aiohttp import web

from thomas.agent.swarm import SwarmConfig, SwarmOrchestrator, SwarmRunRegistry


ToolCall = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]
SwarmEventHook = Callable[[Dict[str, Any]], Awaitable[None]]


def _is_localhost(request: web.Request) -> bool:
    # Most reliable: peername from transport
    peer = None
    try:
        peer = request.transport.get_extra_info("peername") if request.transport else None
    except Exception:
        peer = None
    if peer and isinstance(peer, (tuple, list)) and peer:
        ip = str(peer[0])
    else:
        ip = str(request.remote or "")

    # common loopback forms
    return ip in ("127.0.0.1", "::1", "localhost")


async def handle_cancel(request: web.Request) -> web.Response:
    if not _is_localhost(request):
        raise web.HTTPForbidden(text="cancel endpoint is localhost-only")

    run_id = request.match_info.get("run_id", "")
    if not run_id:
        raise web.HTTPBadRequest(text="missing run_id")

    ok = await SwarmRunRegistry.cancel(run_id)
    return web.json_response({"ok": bool(ok), "run_id": run_id})


async def handle_swarm_chat(
    request: web.Request,
    *,
    payload: Dict[str, Any],
    user_request: str,
    run_id: str,
    session_id: str,
    subagents: Dict[str, Any],
    tool_call: ToolCall,
    tool_mutates_fs: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
    on_event: Optional[SwarmEventHook] = None,
) -> web.StreamResponse:
    """
    NDJSON stream response for Swarm Mode. The caller supplies:
    - run_id, session_id
    - subagents dict (planner/coder/tester/reviewer)
    - tool_call callback (executes existing Thomas tools)
    """

    cfg = SwarmConfig(
        max_parallel_tasks=int(payload.get("swarm_max_parallel", 6)),
        max_parallel_per_agent=payload.get("swarm_max_parallel_per_agent", {}) or {},
        max_tasks=int(payload.get("swarm_max_tasks", 64)),
    )

    orch = SwarmOrchestrator(
        run_id=run_id,
        config=cfg,
        tool_call=tool_call,
        tool_mutates_fs=tool_mutates_fs,
    )

    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "application/x-ndjson; charset=utf-8",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            # Session id can be helpful to the client for correlation
            "X-Session-Id": session_id,
        },
    )
    await resp.prepare(request)

    try:
        async for evt in orch.astream(user_request=user_request, subagents=subagents):
            if on_event is not None:
                with contextlib.suppress(Exception):
                    await on_event(evt)
            line = json.dumps(evt, ensure_ascii=False) + "\n"
            await resp.write(line.encode("utf-8"))
    except (ConnectionResetError, asyncio.CancelledError, BrokenPipeError):
        orch.cancel()
    finally:
        with contextlib.suppress(Exception):
            await resp.write_eof()

    return resp
