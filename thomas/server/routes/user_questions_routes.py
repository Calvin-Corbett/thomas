"""HTTP surface for questions the model asks the person mid-run.

GET  /api/chat/questions              -> {"questions": [...]} still waiting
POST /api/chat/questions/{id}/answer  -> {"selected": [...], "other": ""}; 404 when unknown or already answered

The ``ask_user`` tool awaits the book; these routes are what the chat page
calls when the person taps an option. The chat row registers them.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.core.user_questions import UserQuestionBook, question_book

# After a refused password on a card, the same card cannot prompt again for this long.
REFUSAL_COOLDOWN_S = 30.0


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
        chosen = [str(s) for s in selected]
        verified = False
        if active.needs_password(question_id, chosen):
            refusal = await _password_gate(open_rows.get(question_id) or {}, chosen)
            if refusal:
                # The card stays open: the owner can try again or press No.
                if (open_rows.get(question_id) or {}).get("kind") == "settings-control":
                    from thomas.core.settings_knowledge import provider

                    controls = provider()
                    if controls is not None:
                        controls.sign_in_refused(question_id)
                return web.json_response({"ok": False, "error": refusal, "password": "refused"}, status=403)
            verified = True
        card = open_rows.get(question_id)
        if card and card.get("kind") == "settings-control":
            from thomas.core.settings_knowledge import provider

            controls = provider()
            if controls is None:
                return web.json_response({"error": "Settings self-knowledge is switched off."}, status=409)
            result = await controls.press(question_id, session_id, chosen, verified=verified)
            if not result.get("ok"):
                return web.json_response(result, status=409)
            return web.json_response(result)
        if not active.answer(
            question_id, chosen, other=other, session_id=session_id or None, password_verified=verified
        ):
            return web.json_response({"ok": False, "error": "no such open question"}, status=404)
        return web.json_response({"ok": True, "question_id": question_id})

    prompt_lock = asyncio.Lock()
    refused_at: dict[str, float] = {}

    async def _password_gate(row: dict[str, Any], chosen: list[str]) -> str:
        """Run the one Thomas password prompt for a card answer that needs it.

        Returns "" when Windows accepted the PIN or password, else why not. Only
        this route can mark an answer password_verified, and only after this ran
        in the same request -- which is what makes a password option a wall and
        not a button an agent can post. One prompt at a time, and a refused card
        stays quiet briefly, so nothing can keep asking until the owner gives in.
        """
        qid = str(row.get("id") or "")
        if time.monotonic() - refused_at.get(qid, float("-inf")) < REFUSAL_COOLDOWN_S:
            return "You said no a moment ago. Try again in a few seconds."
        if prompt_lock.locked():
            return "A password prompt is already open. Answer that one first."
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        action = str(details.get("prompt_action") or row.get("question") or "Approve Thomas's request")
        reason = f"You chose: {', '.join(chosen)}."
        from thomas.tools.native_auth import request_native_authorization

        async with prompt_lock:
            ok = await asyncio.get_running_loop().run_in_executor(None, request_native_authorization, action, reason)
        if ok:
            return ""
        refused_at[qid] = time.monotonic()
        return "Not approved at the password prompt."

    app.router.add_get("/api/chat/questions", list_questions)
    app.router.add_post("/api/chat/questions/{question_id}/answer", answer_question)


__all__ = ["setup_user_question_routes"]
