"""HTTP surface for questions the model asks the person mid-run.

GET  /api/chat/questions              -> {"questions": [...]} still waiting
POST /api/chat/questions/{id}/answer  -> {"selected": [...], "other": ""}; 404 when unknown or already answered

The ``ask_user`` tool awaits the book; these routes are what the chat page
calls when the person taps an option. Registered from app_core next to the
overlay routes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.core.user_questions import UserQuestionBook, question_book


def setup_user_question_routes(
    app: web.Application,
    *,
    book: UserQuestionBook | None = None,
    require_api_access: Callable[[web.Request], Any] | None = None,
) -> None:
    active = book or question_book()
    guard = require_api_access or (lambda _request: None)

    async def list_questions(request: web.Request) -> web.Response:
        guard(request)
        # No session id means the session-less (headless) questions only. The
        # book's None, "every session", is for the console answerer and never
        # reachable over HTTP: it broadcast every chat's questions (codex, 2026-09-05).
        session_id = str(request.query.get("session_id") or "").strip()
        return web.json_response({"questions": active.pending(session_id)})

    async def answer_question(request: web.Request) -> web.Response:
        guard(request)
        question_id = str(request.match_info.get("question_id") or "").strip()
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        selected = payload.get("selected")
        if isinstance(selected, str):
            selected = [selected]
        if not isinstance(selected, list):
            selected = []
        other = str(payload.get("other") or "").strip()
        if not selected and not other:
            return web.json_response({"ok": False, "error": "pick an option or type an answer"}, status=400)
        session_id = str(payload.get("session_id") or "").strip()
        open_rows = {q["id"]: q for q in active.pending(None)}
        asked_by = str((open_rows.get(question_id) or {}).get("session_id") or "")
        if asked_by and session_id != asked_by:
            # The page answers with the open chat's id; a question belongs to the
            # chat that asked it, so another tab's answer (or none) is refused.
            return web.json_response({"ok": False, "error": "that question belongs to another chat"}, status=403)
        if not active.answer(question_id, [str(s) for s in selected], other=other, session_id=session_id or None):
            return web.json_response({"ok": False, "error": "no such open question"}, status=404)
        return web.json_response({"ok": True, "question_id": question_id})

    app.router.add_get("/api/chat/questions", list_questions)
    app.router.add_post("/api/chat/questions/{question_id}/answer", answer_question)


__all__ = ["setup_user_question_routes"]
