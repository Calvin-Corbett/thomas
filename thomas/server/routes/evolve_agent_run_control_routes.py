"""Pausing a live Build run, messaging its agents, and answering its questions.

Steer, before this, stopped the run and started a new one: once launched, a run's process could hear nothing. These
handlers write into the run's control folder instead (``thomas/forge/anvil/run_control.py``), which the runner reads
between steps: a pause flag every agent loop holds on, one inbox per agent, and the lead's questions with your
answers. Pausing, messaging and asking all need a lead that runs inside the runner; a Claude Code lead is one
``claude -p`` process, so for it these routes say so instead of pretending (``controls`` in ``/send`` and
``/status`` tells the page in advance).

``GET /messages`` reads the folder from disk, so it still answers after the run ended: a message nobody read by then
reads ``undelivered``, and an open question ``expired``. The live diff (``evolve_agent_live_diff_routes``) is built
with these, because it is the same page asking about the same live run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.event_loop_offload import off_loop
from thomas.forge.anvil import run_control

from .evolve_agent_live_diff_routes import build_live_diff_handlers
from .evolve_agent_run_state import APP_EVOLVE_AGENT_SESSION, APP_EVOLVE_AGENT_TASK, slot_for_run_id, slot_running

_EMPTY_BODY_ERRORS = (json.JSONDecodeError, TypeError, UnicodeDecodeError)
_NOT_ACTIVE = {"ok": False, "error": "that Code run is not active", "code": "run_not_active"}


def session_agent(session: dict[str, Any] | None) -> str:
    """Which agent leads the run: the recorded settings, else what the launcher stamped on the process."""
    session = session or {}
    effective = ((session.get("settings") or {}).get("effective")) or {}
    return str(effective.get("agent") or getattr(session.get("proc"), "thomas_agent", "") or "")


def live_session(app: web.Application, run_id: str) -> dict[str, Any] | None:
    """The session of ``run_id`` while its process is alive, or ``None``."""
    slot = slot_for_run_id(app, run_id)
    if slot is not None:
        return slot.get("session") if slot_running(slot) else None
    legacy = app.get(APP_EVOLVE_AGENT_SESSION)
    if not isinstance(legacy, dict) or str(legacy.get("run_id") or "") != run_id:
        return None
    proc = legacy.get("proc") or app.get(APP_EVOLVE_AGENT_TASK)
    return legacy if proc is not None and proc.returncode is None else None


def build_run_control_handlers(
    app: web.Application,
    require_api_access: Callable[[web.Request], None],
    catalog_root: Callable[[], Path],
    find_conversation: Callable[[Path, str], tuple[Path, dict[str, Any] | None]],
) -> dict[str, Any]:
    """Pause, resume, message, messages and answer, plus the live diff; all against the same catalog root the
    launcher named the run's control folder under."""

    def _folder(run_id: str) -> Path:
        return run_control.control_dir(catalog_root(), run_id)

    async def _body(request: web.Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except _EMPTY_BODY_ERRORS:
            body = {}
        return body if isinstance(body, dict) else {}

    def _run_id(value: Any) -> str:
        run_id = str(value or "").strip()
        return run_id if run_control.valid_id(run_id) else ""

    def _missing_run_id() -> web.Response:
        return web.json_response({"ok": False, "error": "run_id is required", "code": "run_id_required"}, status=400)

    async def _set_paused(request: web.Request, paused: bool) -> web.Response:
        require_api_access(request)
        run_id = _run_id((await _body(request)).get("run_id"))
        if not run_id:
            return _missing_run_id()
        session = live_session(app, run_id)
        if session is None:
            return web.json_response(_NOT_ACTIVE, status=409)
        if paused and not run_control.controls_for_agent(session_agent(session))["pause"]:
            return web.json_response(
                {
                    "ok": False,
                    "code": "pause_unsupported",
                    "error": "Claude Code runs as one process Thomas cannot hold mid-step. Stop it, or let it finish.",
                },
                status=409,
            )
        await off_loop("code_run_control.pause", run_control.set_paused, _folder(run_id), paused)
        return web.json_response({"ok": True, "run_id": run_id, "paused": paused})

    async def pause(request: web.Request) -> web.Response:
        return await _set_paused(request, True)

    async def resume(request: web.Request) -> web.Response:
        return await _set_paused(request, False)

    async def compact(request: web.Request) -> web.Response:
        """Ask the live lead to compact its context at its next step (the context meter's Compact button)."""
        require_api_access(request)
        run_id = _run_id((await _body(request)).get("run_id"))
        if not run_id:
            return _missing_run_id()
        session = live_session(app, run_id)
        if session is None:
            return web.json_response(_NOT_ACTIVE, status=409)
        if not run_control.controls_for_agent(session_agent(session))["pause"]:
            return web.json_response(
                {
                    "ok": False,
                    "code": "compact_unsupported",
                    "error": "Claude Code runs as one process Thomas cannot reach mid-step, so it cannot be told to compact.",
                },
                status=409,
            )
        await off_loop("code_run_control.compact", run_control.request_compaction, _folder(run_id))
        return web.json_response({"ok": True, "run_id": run_id, "requested": True})

    async def context_window(request: web.Request) -> web.Response:
        """Set the context window the live lead works within, in steps of 25,000 (0 returns to the model's own)."""
        require_api_access(request)
        body = await _body(request)
        run_id = _run_id(body.get("run_id"))
        if not run_id:
            return _missing_run_id()
        try:
            wanted = int(body.get("window"))
        except (TypeError, ValueError):
            return web.json_response(
                {"ok": False, "code": "window_required", "error": "window must be a number"}, status=400
            )
        session = live_session(app, run_id)
        if session is None:
            return web.json_response(_NOT_ACTIVE, status=409)
        if not run_control.controls_for_agent(session_agent(session))["pause"]:
            return web.json_response(
                {
                    "ok": False,
                    "code": "context_window_unsupported",
                    "error": "Claude Code runs as one process Thomas cannot reach mid-step, so its window cannot be changed.",
                },
                status=409,
            )
        kept = await off_loop("code_run_control.context_window", run_control.set_context_cap, _folder(run_id), wanted)
        return web.json_response({"ok": True, "run_id": run_id, "window": kept})

    async def message(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await _body(request)
        text = str(body.get("text") or "").strip()
        if not text:
            return web.json_response(
                {"ok": False, "error": "the message is empty", "code": "empty_message"}, status=400
            )
        if len(text) > run_control.MAX_MESSAGE_CHARS:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"messages are limited to {run_control.MAX_MESSAGE_CHARS} characters",
                    "code": "message_too_long",
                },
                status=400,
            )
        run_id = _run_id(body.get("run_id"))
        if not run_id:
            return _missing_run_id()
        agent_id = str(body.get("agent_id") or run_control.LEAD).strip()
        if not run_control.valid_id(agent_id):
            return web.json_response({"ok": False, "error": "unknown agent", "code": "invalid_agent"}, status=400)
        session = live_session(app, run_id)
        if session is None:
            return web.json_response(_NOT_ACTIVE, status=409)
        if not run_control.controls_for_agent(session_agent(session))["message"]:
            reason = "This run's lead is Claude Code, which does not take messages while it works."
        else:
            listening = await off_loop("code_run_control.listening", run_control.listening_agents, _folder(run_id))
            reason = "" if agent_id in listening else "That agent is not listening: it has finished, or not started."
        if reason:
            return web.json_response({"ok": False, "error": reason, "code": "agent_not_listening"}, status=409)
        receipt = await off_loop("code_run_control.message", run_control.queue_message, _folder(run_id), agent_id, text)
        return web.json_response({"ok": True, "receipt": receipt}, status=202)

    async def messages(request: web.Request) -> web.Response:
        require_api_access(request)
        run_id = _run_id(request.query.get("run_id"))
        if not run_id:
            return _missing_run_id()
        running = live_session(app, run_id) is not None
        folder = _folder(run_id)
        if not running and slot_for_run_id(app, run_id) is None and not folder.is_dir():
            return web.json_response({"ok": False, "code": "run_not_found", "run_id": run_id}, status=404)
        state = await off_loop("code_run_control.messages", run_control.snapshot, folder, running=running)
        return web.json_response({"ok": True, "run_id": run_id, "running": running, **state})

    async def answer(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await _body(request)
        run_id = _run_id(body.get("run_id"))
        if not run_id:
            return _missing_run_id()
        question_id = str(body.get("question_id") or "").strip()
        text = str(body.get("answer") or "").strip()
        if not text:
            return web.json_response({"ok": False, "error": "the answer is empty", "code": "empty_answer"}, status=400)
        if len(text) > run_control.MAX_MESSAGE_CHARS:
            return web.json_response(
                {"ok": False, "error": "the answer is too long", "code": "answer_too_long"}, status=400
            )
        running = live_session(app, run_id) is not None
        result = await off_loop(
            "code_run_control.answer", run_control.submit_answer, _folder(run_id), question_id, text, running=running
        )
        if result == "not_found":
            return web.json_response(
                {"ok": False, "error": "no such question", "code": "question_not_found"}, status=404
            )
        if result == "not_open":
            return web.json_response(
                {"ok": False, "error": "that question is no longer open", "code": "question_not_open"}, status=409
            )
        return web.json_response({"ok": True, "run_id": run_id, "question_id": question_id})

    async def performance(request: web.Request) -> web.Response:
        """Tokens per day, how fast the lead goes and how soon it speaks, over the last days' runs (read-only)."""
        require_api_access(request)
        try:
            days = max(1, min(30, int(request.query.get("days") or 7)))
        except ValueError:
            days = 7
        summary = await off_loop("code_run_control.performance", run_control.usage_summary, catalog_root(), days)
        return web.json_response({"ok": True, **summary})

    handlers: dict[str, Any] = {
        "run_pause": pause,
        "run_resume": resume,
        "run_message": message,
        "run_messages": messages,
        "run_answer": answer,
        "run_performance": performance,
        "run_compact": compact,
        "run_context_window": context_window,
    }
    handlers.update(build_live_diff_handlers(app, require_api_access, catalog_root, find_conversation))
    return handlers


__all__ = ["build_run_control_handlers", "live_session", "session_agent"]
