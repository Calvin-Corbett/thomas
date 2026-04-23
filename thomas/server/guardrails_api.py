from __future__ import annotations

from typing import Any

from aiohttp import web

from thomas.agent.approval import ApprovalBroker


def _parse_decision(payload: dict[str, Any], *, default: bool | None = None) -> bool | None:
    if not isinstance(payload, dict):
        return default
    if "decision" in payload:
        value = payload.get("decision")
    elif "approved" in payload:
        value = payload.get("approved")
    elif "approve" in payload:
        value = payload.get("approve")
    else:
        value = None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "ok", "allow", "approve"):
            return True
        if v in ("0", "false", "no", "fail", "failed", "deny", "reject"):
            return False
    return default


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
        if not isinstance(data, dict):
            data = {}

        run_id = str(data.get("run_id") or "")
        tool_call_id = str(data.get("tool_call_id") or "")
        decision = _parse_decision(data, default=None)
        allow_session_tool = bool(data.get("allow_session_tool", False))
        tool_name = data.get("tool_name")
        session_id = data.get("session_id")

        if not run_id or not tool_call_id or decision is None:
            return web.json_response(
                {"ok": False, "error": "missing run_id/tool_call_id or invalid decision"}, status=400
            )

        ok = await approvals.resolve(
            run_id=run_id,
            tool_call_id=tool_call_id,
            approved=bool(decision),
            allow_session_tool=allow_session_tool,
            tool_name=tool_name,
            session_id=session_id,
        )
        return web.json_response({"ok": True, "resolved": ok})

    app.router.add_get("/api/approvals/pending", pending)
    app.router.add_post("/api/approvals/resolve", resolve)
