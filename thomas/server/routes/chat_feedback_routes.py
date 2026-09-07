"""Thumbs up or down on a reply (frontier parity: ChatGPT, Claude.ai).

POST /api/chat/feedback  {"session_id"?, "message_id", "rating": "up"|"down", "note"?}
GET  /api/chat/feedback?limit=N  -> {"feedback": [...]} newest first

One JSON object per line in ``.thomas/feedback.jsonl`` under the data dir, so
the self-review report can read what the person thought of real replies.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

_RATINGS = {"up", "down"}


def _read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def setup_chat_feedback_routes(
    app: web.Application,
    *,
    store_path: Path,
    require_api_access: Callable[[web.Request], Any] | None = None,
) -> None:
    guard = require_api_access or (lambda _request: None)
    store = Path(store_path)

    async def post_feedback(request: web.Request) -> web.Response:
        guard(request)
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        rating = str(payload.get("rating") or "").strip().lower()
        message_id = str(payload.get("message_id") or "").strip()
        if rating not in _RATINGS or not message_id:
            return web.json_response(
                {"ok": False, "error": "message_id and a rating of up or down are required"}, status=400
            )
        row = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": str(payload.get("session_id") or "").strip()[:128],
            "message_id": message_id[:128],
            "rating": rating,
            "note": str(payload.get("note") or "").strip()[:2000],
        }
        try:
            store.parent.mkdir(parents=True, exist_ok=True)
            with store.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as exc:
            return web.json_response({"ok": False, "error": f"could not save feedback: {exc}"}, status=500)
        return web.json_response({"ok": True, "feedback": row})

    async def list_feedback(request: web.Request) -> web.Response:
        guard(request)
        try:
            limit = max(1, min(500, int(request.query.get("limit") or 50)))
        except ValueError:
            limit = 50
        rows = _read_rows(store)
        rows.reverse()
        return web.json_response({"feedback": rows[:limit], "total": len(rows)})

    app.router.add_post("/api/chat/feedback", post_feedback)
    app.router.add_get("/api/chat/feedback", list_feedback)


__all__ = ["setup_chat_feedback_routes"]
