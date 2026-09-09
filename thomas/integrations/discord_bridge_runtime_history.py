"""History and search helpers for the Discord bridge runtime."""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any

from thomas.integrations.discord_bridge_runtime_support import (
    _HISTORY_RESULT_LIMIT_MAX,
    _now_utc_iso,
    _safe_text,
)


class DiscordBridgeRuntimeHistoryMixin:
    """Conversation history indexing and lookup helpers."""

    def append_history_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        assistant_text: str,
        context: dict[str, Any] | None = None,
        tool_calls: int | None = None,
    ) -> dict[str, Any] | None:
        sid = _safe_text(session_id)
        user_msg = str(user_text or "")
        assistant_msg = str(assistant_text or "")
        if not sid or (not user_msg and not assistant_msg):
            return None
        ctx = context or {}
        row = {
            "turn_id": f"discord-{uuid.uuid4().hex[:16]}",
            "created_at": _now_utc_iso(),
            "session_id": sid,
            "scope_key": _safe_text(ctx.get("scope_key")),
            "user_id": _safe_text(ctx.get("user_id")),
            "display_name": _safe_text(ctx.get("display_name")),
            "guild_id": _safe_text(ctx.get("guild_id")),
            "channel_id": _safe_text(ctx.get("channel_id")),
            "surface": _safe_text(ctx.get("surface")) or "discord",
            "request_kind": _safe_text(ctx.get("request_kind")) or "message",
            "owner": bool(ctx.get("owner")),
            "granted_capabilities": list(ctx.get("granted_capabilities") or []),
            "tool_calls": int(tool_calls or 0),
            "user_text": user_msg,
            "assistant_text": assistant_msg,
        }
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def _iter_history_rows(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            lines = self.history_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        for line in lines:
            text = _safe_text(line)
            if not text:
                continue
            with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                payload = json.loads(text)
                if isinstance(payload, dict):
                    rows.append(payload)
        return rows

    def _history_match(self, row: dict[str, Any], query: str) -> bool:
        q = _safe_text(query).lower()
        if not q:
            return True
        blob = " ".join(
            [
                _safe_text(row.get("session_id")),
                _safe_text(row.get("scope_key")),
                _safe_text(row.get("display_name")),
                _safe_text(row.get("user_text")),
                _safe_text(row.get("assistant_text")),
            ]
        ).lower()
        return all(token in blob for token in q.split())

    def _history_excerpt(self, row: dict[str, Any], query: str) -> str:
        body = " ".join(
            part for part in [_safe_text(row.get("user_text")), _safe_text(row.get("assistant_text"))] if part
        ).strip()
        if not body:
            return ""
        q = _safe_text(query)
        if not q:
            return body[:220]
        lower_body = body.lower()
        lower_q = q.lower()
        idx = lower_body.find(lower_q)
        if idx < 0:
            return body[:220]
        start = max(0, idx - 80)
        end = min(len(body), idx + len(q) + 120)
        excerpt = body[start:end].strip()
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(body):
            excerpt = excerpt + "..."
        return excerpt

    def search_history(
        self,
        *,
        query: str = "",
        limit: int = 20,
        session_id: str = "",
    ) -> list[dict[str, Any]]:
        resolved_limit = max(1, min(int(limit or 20), _HISTORY_RESULT_LIMIT_MAX))
        resolved_session_id = _safe_text(session_id)
        hits: list[dict[str, Any]] = []
        for row in reversed(self._iter_history_rows()):
            if resolved_session_id and _safe_text(row.get("session_id")) != resolved_session_id:
                continue
            if not self._history_match(row, query):
                continue
            hits.append(
                {
                    "turn_id": _safe_text(row.get("turn_id")),
                    "created_at": _safe_text(row.get("created_at")),
                    "session_id": _safe_text(row.get("session_id")),
                    "scope_key": _safe_text(row.get("scope_key")),
                    "display_name": _safe_text(row.get("display_name")),
                    "surface": _safe_text(row.get("surface")),
                    "request_kind": _safe_text(row.get("request_kind")),
                    "owner": bool(row.get("owner")),
                    "tool_calls": int(row.get("tool_calls") or 0),
                    "excerpt": self._history_excerpt(row, query),
                }
            )
            if len(hits) >= resolved_limit:
                break
        return hits

    def list_sessions(self, *, limit: int = 20, query: str = "") -> list[dict[str, Any]]:
        resolved_limit = max(1, min(int(limit or 20), _HISTORY_RESULT_LIMIT_MAX))
        grouped: dict[str, dict[str, Any]] = {}
        for row in self._iter_history_rows():
            if not self._history_match(row, query):
                continue
            session_id = _safe_text(row.get("session_id"))
            if not session_id:
                continue
            item = grouped.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "scope_key": _safe_text(row.get("scope_key")),
                    "display_name": _safe_text(row.get("display_name")),
                    "guild_id": _safe_text(row.get("guild_id")),
                    "channel_id": _safe_text(row.get("channel_id")),
                    "surface": _safe_text(row.get("surface")) or "discord",
                    "request_kinds": set(),
                    "turn_count": 0,
                    "updated_at": _safe_text(row.get("created_at")),
                    "preview": "",
                },
            )
            item["turn_count"] = int(item.get("turn_count") or 0) + 1
            item["updated_at"] = _safe_text(row.get("created_at")) or item["updated_at"]
            item["preview"] = _safe_text(row.get("assistant_text") or row.get("user_text")) or item["preview"]
            request_kind = _safe_text(row.get("request_kind"))
            if request_kind:
                item["request_kinds"].add(request_kind)
        sessions = []
        for item in grouped.values():
            item["request_kinds"] = sorted(item["request_kinds"])
            sessions.append(item)
        sessions.sort(key=lambda row: _safe_text(row.get("updated_at")), reverse=True)
        return sessions[:resolved_limit]

    def get_session_context(self, session_id: str, *, limit: int = 12) -> dict[str, Any]:
        resolved_session_id = _safe_text(session_id)
        resolved_limit = max(1, min(int(limit or 12), _HISTORY_RESULT_LIMIT_MAX))
        turns = [row for row in self._iter_history_rows() if _safe_text(row.get("session_id")) == resolved_session_id]
        turns = turns[-resolved_limit:]
        session_rows = self.list_sessions(limit=1_000, query="")
        session = next((row for row in session_rows if _safe_text(row.get("session_id")) == resolved_session_id), None)
        output_turns = [
            {
                "turn_id": _safe_text(row.get("turn_id")),
                "created_at": _safe_text(row.get("created_at")),
                "display_name": _safe_text(row.get("display_name")),
                "request_kind": _safe_text(row.get("request_kind")),
                "owner": bool(row.get("owner")),
                "tool_calls": int(row.get("tool_calls") or 0),
                "user_text": _safe_text(row.get("user_text")),
                "assistant_text": _safe_text(row.get("assistant_text")),
            }
            for row in turns
        ]
        return {
            "session": session or {"session_id": resolved_session_id},
            "turns": output_turns,
        }
