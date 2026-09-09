"""The store's optional UX layer: operator messages and briefings.

Split out of ``store.py`` on 2026-09-05 so the store could take the cancel
boundary its finalizers need without crossing the monolith guard. The four
methods are unchanged; ``AutonomyStore`` mixes them in and they use its lock
and connection.
"""

from __future__ import annotations

import json
import uuid
from typing import Any


class NotesStoreMixin:
    """Messages and briefings on top of an ``AutonomyStore`` connection."""

    _conn: Any
    _lock: Any

    def add_message(self, *, session_id: str | None, level: str, text: str) -> str:
        from thomas.marketplace.autonomy.store import _dt_to_str, _utcnow

        now = _utcnow()
        mid = uuid.uuid4().hex
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO autonomy_messages(id,session_id,ts,level,text) VALUES (?,?,?,?,?);",
                (mid, session_id, _dt_to_str(now), level, text),
            )
            cur.close()
        return mid

    def list_messages(self, *, limit: int = 200, session_id: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM autonomy_messages"
        args: list[Any] = []
        if session_id:
            q += " WHERE session_id=?"
            args.append(session_id)
        q += " ORDER BY ts DESC LIMIT ?;"
        args.append(int(limit))

        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(q, tuple(args)).fetchall()
            cur.close()
        return [
            {"id": r["id"], "session_id": r["session_id"], "ts": r["ts"], "level": r["level"], "text": r["text"]}
            for r in rows
        ]

    def add_briefing(self, *, content: dict[str, Any]) -> str:
        from thomas.marketplace.autonomy.store import _dt_to_str, _utcnow

        now = _utcnow()
        bid = uuid.uuid4().hex
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO briefings(id,ts,content_json) VALUES (?,?,?);",
                (bid, _dt_to_str(now), json.dumps(content or {}, separators=(",", ":"), ensure_ascii=False)),
            )
            cur.close()
        return bid

    def list_briefings(self, *, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute("SELECT * FROM briefings ORDER BY ts DESC LIMIT ?;", (int(limit),)).fetchall()
            cur.close()
        return [{"id": r["id"], "ts": r["ts"], "content": json.loads(r["content_json"] or "{}")} for r in rows]
