from __future__ import annotations

import json
from aiohttp import web
from typing import Any, Dict

from thomas.agent.approval import ApprovalBroker

def _is_localhost(request: web.Request) -> bool:
    peer = request.transport.get_extra_info("peername") if request.transport else None
    host = None
    if isinstance(peer, tuple) and peer:
        host = peer[0]
    # If we can't determine, be conservative.
    if not host:
        return False
    return host in ("127.0.0.1", "::1")

def install_guardrails_routes(app: web.Application, approvals: ApprovalBroker) -> None:
    async def pending(request: web.Request) -> web.Response:
        if not _is_localhost(request):
            return web.json_response({"ok": False, "error": "localhost only"}, status=403)
        return web.json_response({"ok": True, "pending": await approvals.pending()})

    async def resolve(request: web.Request) -> web.Response:
        if not _is_localhost(request):
            return web.json_response({"ok": False, "error": "localhost only"}, status=403)
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        run_id = str(data.get("run_id") or "")
        tool_call_id = str(data.get("tool_call_id") or "")
        decision = str(data.get("decision") or "").lower()
        allow_session_tool = bool(data.get("allow_session_tool", False))
        tool_name = data.get("tool_name")
        session_id = data.get("session_id")

        if not run_id or not tool_call_id or decision not in ("approve", "deny"):
            return web.json_response({"ok": False, "error": "missing run_id/tool_call_id or invalid decision"}, status=400)

        ok = await approvals.resolve(
            run_id=run_id,
            tool_call_id=tool_call_id,
            approved=(decision == "approve"),
            allow_session_tool=allow_session_tool,
            tool_name=tool_name,
            session_id=session_id,
        )
        return web.json_response({"ok": True, "resolved": ok})

    app.router.add_get("/api/approvals/pending", pending)
    app.router.add_post("/api/approvals/resolve", resolve)
