"""The task-ledger and diagnostics handlers, built for ``app_routes_init``.

Six handlers (the task ledger's current and history views, the mutating
route policy snapshot, landing health, engines and tools)
lived as nested functions inside ``_setup_routes_and_handlers``. The initializer still
registers the security snapshot by name, and ``task_ledger_routes.py`` and
``server_diagnostics_routes.py`` register the rest for their rows, so this returns the
handlers in a dict rather than registering anything itself. The second inner cut of that
1,382-line function.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.server.app_keys import (
    APP_ENGINE_MANAGER,
    APP_MUTATING_ROUTE_POLICY_SNAPSHOT,
    APP_SESSIONS,
    APP_TASK_LEDGER,
    APP_TOOLS,
    ChatSession,
)
from thomas.tools.registry import ToolRegistry


def build_task_ledger_handlers(
    app: web.Application, *, require_api_access: Callable[..., Any]
) -> dict[str, Callable[..., Any]]:
    """Return the six handlers keyed by the names the registrars use."""
    _require_api_access = require_api_access

    async def api_task_ledger_current(request: web.Request) -> web.Response:
        """Return current task ledger snapshot for a session (or latest session)."""
        _require_api_access(request)
        ledger = app.get(APP_TASK_LEDGER)
        if not ledger:
            raise web.HTTPNotFound(text="task ledger unavailable")

        session_id = str(request.query.get("session_id", "")).strip()
        snapshot_obj = ledger.get_current(session_id) if session_id else ledger.get_latest()
        snapshot = snapshot_obj.to_dict() if snapshot_obj and hasattr(snapshot_obj, "to_dict") else None
        if isinstance(snapshot, dict):
            snapshot.setdefault("missing_inputs", [])
        resolved_session_id = str(
            session_id or getattr(snapshot_obj, "session_id", "") or (snapshot or {}).get("session_id") or ""
        ).strip()
        sessions = app.get(APP_SESSIONS, {})
        session_obj = sessions.get(resolved_session_id) if isinstance(sessions, dict) and resolved_session_id else None
        task_definition = (
            dict(getattr(session_obj, "task_definition", {}) or {}) if isinstance(session_obj, ChatSession) else None
        )
        task_evaluation = (
            dict(getattr(session_obj, "task_evaluation", {}) or {}) if isinstance(session_obj, ChatSession) else None
        )
        benchmark_session = (
            dict(getattr(session_obj, "benchmark_session", {}) or {}) if isinstance(session_obj, ChatSession) else None
        )
        task_definition_status = (
            str(getattr(session_obj, "task_definition_status", "idle") or "idle")
            if isinstance(session_obj, ChatSession)
            else "idle"
        )
        return web.json_response(
            {
                "ok": True,
                "session_id": resolved_session_id,
                "state": snapshot,
                "snapshot": snapshot,
                "task_definition_status": task_definition_status,
                "task_definition": task_definition,
                "task_evaluation": task_evaluation,
                "benchmark_session": benchmark_session,
            }
        )

    async def api_task_ledger_history(request: web.Request) -> web.Response:
        """Return task ledger history for a session (or latest session)."""
        _require_api_access(request)
        ledger = app.get(APP_TASK_LEDGER)
        if not ledger:
            raise web.HTTPNotFound(text="task ledger unavailable")

        session_id = str(request.query.get("session_id", "")).strip()
        if not session_id:
            latest = ledger.get_latest()
            session_id = str(getattr(latest, "session_id", "") or "").strip()
        try:
            limit = max(1, min(int(str(request.query.get("limit", "50") or "50")), 200))
        except (TypeError, ValueError) as e:
            raise web.HTTPBadRequest(text="invalid limit") from e

        history = ledger.get_history(session_id, limit=limit) if session_id else []
        return web.json_response(
            {
                "ok": True,
                "session_id": session_id,
                "events": history,
                "history": history,
            }
        )

    async def api_security_mutating_routes(request: web.Request) -> web.Response:
        """Return security policy snapshot for mutating routes."""
        _require_api_access(request)
        snapshot = app.get(APP_MUTATING_ROUTE_POLICY_SNAPSHOT, {})
        return web.json_response(snapshot)

    async def api_landing_health(request: web.Request) -> web.Response:
        """Return the landing heartbeat: is the owner's work landed, or piling up?

        The same reading the server logs at startup, so the UI can show it
        rather than relying on anyone having read the log. The git work is
        blocking, so it runs in a thread and never stalls the event loop.

        Carries the last push of dev to GitHub too: ``github_push`` (status, level, ``sentence`` in plain words, how far
        GitHub is behind) and the same sentence as the last of ``sentences``.

        Carries the event-loop figures too: ``event_loop`` is how late the loop
        woke a coroutine that asked for a quarter second (the honest measure of
        "the server stopped answering"), and ``off_loop`` is how much blocking
        work was kept off it. Both are readable without a debugger attached,
        which is the only reason a regression here would ever be noticed.
        """
        _require_api_access(request)
        from thomas.core.event_loop_lag import lag_snapshot
        from thomas.core.event_loop_offload import offload_summary
        from thomas.core.github_push_status import collect_github_push
        from thomas.core.landing_health import collect_landing_health

        health = await asyncio.to_thread(collect_landing_health)
        github_push = await asyncio.to_thread(collect_github_push)
        body = health.as_dict()
        if isinstance(body.get("sentences"), list):  # a page that lists the sentences shows this one too
            body["sentences"] = [*body["sentences"], github_push["sentence"]]
        return web.json_response(
            {**body, "github_push": github_push, "event_loop": lag_snapshot(), "off_loop": offload_summary()}
        )

    async def api_engines(request: web.Request) -> web.Response:
        """Return engine manager status and results."""
        _require_api_access(request)
        engine_manager = app.get(APP_ENGINE_MANAGER)
        if not engine_manager:
            return web.json_response({"status": "unavailable"})
        return web.json_response({"status": "ok", "engines": engine_manager.status()})

    async def api_tools(request: web.Request) -> web.Response:
        """List all registered tools."""
        _require_api_access(request)
        registry: ToolRegistry | None = app.get(APP_TOOLS)
        if not registry:
            return web.json_response({"tools": [], "count": 0})

        tools_list = []
        for tool in registry.list_tools():
            parameters = getattr(tool, "parameters", {})
            if not isinstance(parameters, dict):
                parameters = {}
            tool_dict = {
                "id": getattr(tool, "name", ""),
                "name": getattr(tool, "name", ""),
                "description": getattr(tool, "description", ""),
                "category": getattr(tool, "category", ""),
                "status": "active",
                "params": parameters,
                "parameters": parameters,
            }
            tools_list.append(tool_dict)
        return web.json_response({"tools": tools_list, "count": len(tools_list)})

    return {
        "api_task_ledger_current": api_task_ledger_current,
        "api_task_ledger_history": api_task_ledger_history,
        "api_security_mutating_routes": api_security_mutating_routes,
        "api_landing_health": api_landing_health,
        "api_engines": api_engines,
        "api_tools": api_tools,
    }
