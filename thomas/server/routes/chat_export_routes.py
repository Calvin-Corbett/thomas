"""Export a chat as a file the person owns (frontier parity: ChatGPT and Claude export).

GET /api/chats/{chat_id}/export?format=md|json|html[&title=...]

Reads the live v2 session store (``.thomas/sessions_v2/chat_<hex>.json``) and
returns Markdown by default, JSON or a self-contained read-only HTML page on
request, as an attachment. The chat id is the sidebar's session id or the
store's ``chat_<hex>`` file stem; anything else is refused before a path is built.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

# The sidebar carries the raw v2 session id (24 url-safe chars); the store
# names the file chat_<sha256(session_id)[:16]>.json (thomas/chat/session_store.py).
# Either form is accepted; the first version accepted only the file stem and
# answered 400 for every real chat (found live 2026-09-05).
_CHAT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_FILE_STEM = re.compile(r"^chat_[0-9a-f]{16}$")


def session_file_for(sessions_dir: Path, chat_id: str) -> Path | None:
    """The session file behind a sidebar id or a file stem; None when the id is malformed."""
    import hashlib

    chat_id = str(chat_id or "").strip()
    if not _CHAT_ID.fullmatch(chat_id):
        return None
    root = Path(sessions_dir)
    if _FILE_STEM.fullmatch(chat_id) and (root / f"{chat_id}.json").exists():
        return root / f"{chat_id}.json"
    return root / f"chat_{hashlib.sha256(chat_id.encode()).hexdigest()[:16]}.json"


def _when(session: dict[str, Any]) -> str:
    meta = session.get("meta") if isinstance(session.get("meta"), dict) else {}
    raw = meta.get("created_at") or session.get("saved_at") or ""
    try:
        if isinstance(raw, (int, float)) or (isinstance(raw, str) and re.fullmatch(r"\d+(\.\d+)?", raw)):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if isinstance(raw, str) and raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, OverflowError, OSError):
        pass
    return str(raw)


def _messages(session: dict[str, Any]) -> list[dict[str, Any]]:
    conversation = session.get("conversation")
    if isinstance(conversation, dict):
        conversation = conversation.get("messages")
    if not isinstance(conversation, list):
        return []
    return [m for m in conversation if isinstance(m, dict)]


def _title(session: dict[str, Any], override: str = "") -> str:
    if override.strip():
        return override.strip()[:200]
    meta = session.get("meta") if isinstance(session.get("meta"), dict) else {}
    if str(meta.get("title") or "").strip():
        return str(meta["title"]).strip()[:200]
    for message in _messages(session):
        if message.get("role") == "user" and str(message.get("content") or "").strip():
            first = str(message["content"]).strip().splitlines()[0]
            return (first[:77] + "...") if len(first) > 80 else first
    return str(session.get("session_id") or "Thomas chat")


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False, default=str) if content is not None else ""


def render_markdown(session: dict[str, Any], *, title: str = "") -> str:
    meta = session.get("meta") if isinstance(session.get("meta"), dict) else {}
    lines = [f"# {_title(session, title)}", ""]
    model = str(meta.get("model_id") or meta.get("model") or "").strip()
    header = [f"Exported from Thomas on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}."]
    if model:
        header.append(f"Model: {model}.")
    when = _when(session)
    if when:
        header.append(f"Started: {when}.")
    lines.append(" ".join(header))
    lines.append("")
    for message in _messages(session):
        role = str(message.get("role") or "").strip().lower()
        if role == "user":
            lines.append("## You")
        elif role == "assistant":
            lines.append("## Thomas")
        elif role == "tool":
            lines.append(f"### Tool result: {message.get('name') or message.get('tool_name') or 'tool'}")
        elif role == "system":
            continue
        else:
            lines.append(f"## {role or 'message'}")
        text = _content_text(message.get("content")).strip()
        if text:
            if role == "tool":
                lines.append("```")
                lines.append(text[:4000])
                lines.append("```")
            else:
                lines.append(text)
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict):
                name = call.get("name") or (call.get("function") or {}).get("name") or "tool"
                lines.append(f"- called `{name}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(session: dict[str, Any], *, title: str = "") -> str:
    """One self-contained, read-only page of the chat: no scripts, no outside resources.

    The local-first form of a shareable thread snapshot (Codex thread snapshots,
    Claude share): a file the person can send, that shows the same in any
    browser and can run nothing. Every string from the chat is escaped.
    """
    from html import escape

    meta = session.get("meta") if isinstance(session.get("meta"), dict) else {}
    heading = escape(_title(session, title))
    model = escape(str(meta.get("model_id") or meta.get("model") or "").strip())
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    note = f"Exported from Thomas on {stamp}." + (f" Model: {model}." if model else "")
    when = _when(session)
    if when:
        note += f" Started: {escape(when)}."
    turns: list[str] = []
    for message in _messages(session):
        role = str(message.get("role") or "").strip().lower()
        if role == "system":
            continue
        who = {"user": "You", "assistant": "Thomas", "tool": "Tool result"}.get(role, role or "message")
        text = _content_text(message.get("content")).strip()
        if role == "tool":
            text = text[:4000]
        body = escape(text)
        calls = [
            escape(str(call.get("name") or (call.get("function") or {}).get("name") or "tool"))
            for call in (message.get("tool_calls") or [])
            if isinstance(call, dict)
        ]
        if calls:
            body += ("\n" if body else "") + "called: " + ", ".join(calls)
        css_role = role if role in {"user", "assistant", "tool"} else "other"
        turns.append(f'<section class="turn {css_role}"><h2>{escape(who)}</h2><pre>{body}</pre></section>')
    style = (
        "body{max-width:52rem;margin:2rem auto;padding:0 1rem;font:16px/1.5 system-ui,sans-serif;color:#1c1e26;background:#fafafa}"
        "h1{font-size:1.4rem}p.note{color:#666;font-size:.9rem}"
        ".turn{margin:1rem 0;padding:.8rem 1rem;border-radius:12px;border:1px solid #ddd;background:#fff}"
        ".turn.user{background:#eef2ff}.turn h2{margin:0 0 .4rem;font-size:.85rem;letter-spacing:.04em;text-transform:uppercase;color:#555}"
        ".turn pre{margin:0;white-space:pre-wrap;word-wrap:break-word;font:inherit}"
        "@media (prefers-color-scheme:dark){body{color:#e6e6e6;background:#15171c}.turn{background:#1e2129;border-color:#333}.turn.user{background:#232a3d}.turn h2{color:#aaa}p.note{color:#999}}"
    )
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{heading}</title><style>{style}</style></head><body>"
        f'<h1>{heading}</h1><p class="note">{note}</p>' + "".join(turns) + "</body></html>\n"
    )


def setup_chat_export_routes(
    app: web.Application,
    *,
    sessions_dir: Path,
    require_api_access: Callable[[web.Request], Any] | None = None,
) -> None:
    guard = require_api_access or (lambda _request: None)
    root = Path(sessions_dir)

    async def export_chat(request: web.Request) -> web.Response:
        guard(request)
        chat_id = str(request.match_info.get("chat_id") or "").strip()
        path = session_file_for(root, chat_id)
        if path is None:
            return web.json_response({"ok": False, "error": "chat id must be a session id or chat_<hex>"}, status=400)
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return web.json_response({"ok": False, "error": "no such chat"}, status=404)
        if not isinstance(session, dict):
            return web.json_response({"ok": False, "error": "no such chat"}, status=404)
        fmt = str(request.query.get("format") or "md").strip().lower()
        title = str(request.query.get("title") or "")
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", _title(session, title)).strip("-")[:60] or chat_id
        if fmt == "json":
            body = json.dumps(session, ensure_ascii=False, indent=2, default=str)
            return web.Response(
                text=body,
                content_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
            )
        if fmt == "html":
            return web.Response(
                text=render_html(session, title=title),
                content_type="text/html",
                charset="utf-8",
                headers={"Content-Disposition": f'attachment; filename="{stem}.html"'},
            )
        return web.Response(
            text=render_markdown(session, title=title),
            content_type="text/markdown",
            charset="utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.md"'},
        )

    app.router.add_get("/api/chats/{chat_id}/export", export_chat)


__all__ = ["session_file_for", "render_html", "render_markdown", "setup_chat_export_routes"]
