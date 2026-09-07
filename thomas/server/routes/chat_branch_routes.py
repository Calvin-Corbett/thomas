"""Branch a chat into a new chat (frontier parity: ChatGPT and Claude.ai branch from a message).

POST /api/chats/{chat_id}/branch  body {"upto": N} optional
  -> {"ok": true, "chat_id": "chat_<hex>", "messages": N}

Copies the live v2 session file (``.thomas/sessions_v2/chat_<hex>.json``) to a
fresh id, keeping the first ``upto`` messages (all of them by default), the
model and settings, and none of the run log. The original is not touched.
The sidebar's "Branch this chat" action calls this and opens the copy.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.server.routes.chat_export_routes import session_file_for


def branch_session(session: dict[str, Any], *, new_id: str, upto: int | None) -> dict[str, Any]:
    """The copy: first ``upto`` messages, fresh identity, no run log."""
    conversation = dict(session.get("conversation") or {}) if isinstance(session.get("conversation"), dict) else {}
    messages = [m for m in (conversation.get("messages") or []) if isinstance(m, dict)]
    if upto is not None:
        messages = messages[:upto]
    conversation["messages"] = messages
    conversation["message_count"] = len(messages)
    meta = dict(session.get("meta") or {}) if isinstance(session.get("meta"), dict) else {}
    now = time.time()
    meta.update(
        {
            "session_id": new_id,
            "branched_from": str(session.get("session_id") or ""),
            "created_at": now,
            "updated_at": now,
            "total_turns": sum(1 for m in messages if m.get("role") == "user"),
        }
    )
    copy = {k: v for k, v in session.items() if k != "session_log"}
    copy.update({"session_id": new_id, "saved_at": now, "conversation": conversation, "meta": meta})
    return copy


def setup_chat_branch_routes(
    app: web.Application,
    *,
    sessions_dir: Path,
    require_api_access: Callable[[web.Request], Any] | None = None,
) -> None:
    root = Path(sessions_dir)
    guard = require_api_access or (lambda _request: None)

    async def branch_chat(request: web.Request) -> web.Response:
        guard(request)
        chat_id = str(request.match_info.get("chat_id") or "").strip()
        source = session_file_for(root, chat_id)
        if source is None:
            return web.json_response({"ok": False, "error": "chat id must be a session id or chat_<hex>"}, status=400)
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        upto: int | None = None
        if payload.get("upto") is not None:
            try:
                upto = int(payload["upto"])
            except (TypeError, ValueError):
                upto = 0
            if upto < 1:
                return web.json_response({"ok": False, "error": "upto must be a positive message count"}, status=400)
        try:
            session = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return web.json_response({"ok": False, "error": "no such chat"}, status=404)
        if not isinstance(session, dict):
            return web.json_response({"ok": False, "error": "no such chat"}, status=404)
        # A store-style id (24 url-safe chars) and the store's file name for it.
        new_id = secrets.token_urlsafe(18)
        copy = branch_session(session, new_id=new_id, upto=upto)
        copy["meta"]["branched_from"] = str(session.get("session_id") or chat_id)
        target = root / f"chat_{hashlib.sha256(new_id.encode()).hexdigest()[:16]}.json"
        try:
            target.write_text(json.dumps(copy, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            return web.json_response({"ok": False, "error": f"could not write the branch: {exc}"}, status=500)
        return web.json_response({"ok": True, "chat_id": new_id, "messages": len(copy["conversation"]["messages"])})

    app.router.add_post("/api/chats/{chat_id}/branch", branch_chat)


__all__ = ["branch_session", "setup_chat_branch_routes"]
