"""The disk-backed chat store behind the web app's chat-history routes.

Extracted from ``thomas.server.app_middleware_handlers`` to keep that module
under the architecture size limit. Everything here used to be an inline closure
in ``setup_middleware_and_handlers``; ``build_chat_store`` returns the same
closures over the same two pieces of state (the store directory and the lock
that serialises access to it), so the on-disk format, the sanitising rules and
the locking discipline are unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def build_chat_store(
    chat_store_dir: Path,
    chat_store_lock: asyncio.Lock,
) -> dict[str, Callable[..., Any]]:
    """Build the disk-backed chat-store helpers for the web app.

    Returns a mapping of helper name -> callable, keyed by the same names the
    route wiring in ``app_routes_init`` looks up. ``_safe_int`` and
    ``_clone_json`` stay private to this module because nothing outside the
    store uses them.
    """
    from aiohttp import web

    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _clone_json(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _chat_file_for(chat_id: str) -> Path:
        digest = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()
        return chat_store_dir / f"{digest}.json"

    def _sanitize_chat_payload(payload: dict[str, Any], chat_id: str = "") -> dict[str, Any]:
        """Validate and sanitize a chat payload."""
        requested_id = str(payload.get("id") or "").strip()
        if not requested_id:
            raise web.HTTPBadRequest(text="missing chat id")
        if len(requested_id) > 160:
            raise web.HTTPBadRequest(text="chat id is too long")

        resolved_id = str(chat_id or requested_id).strip()
        if not resolved_id:
            raise web.HTTPBadRequest(text="missing chat id")
        if len(resolved_id) > 160:
            raise web.HTTPBadRequest(text="chat id is too long")
        if requested_id and requested_id != resolved_id:
            raise web.HTTPBadRequest(text="chat id mismatch")

        now_ms = int(time.time() * 1000)
        created_at = _safe_int(payload.get("createdAt"), now_ms)
        updated_at = _safe_int(payload.get("updatedAt"), now_ms)
        updated_at = max(updated_at, created_at)

        title = str(payload.get("title") or "New Chat").strip() or "New Chat"
        if len(title) > 200:
            title = title[:200]

        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            raise web.HTTPBadRequest(text="messages must be a list")

        messages: list[dict[str, Any]] = []
        for msg in raw_messages[:2000]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip()
            if role not in ("user", "assistant"):
                continue

            entry: dict[str, Any] = {
                "id": str(msg.get("id") or secrets.token_urlsafe(8)),
                "role": role,
                "createdAt": _safe_int(msg.get("createdAt"), now_ms),
                "status": str(msg.get("status") or "complete").strip() or "complete",
            }

            content = msg.get("content", "")
            if isinstance(content, str):
                entry["content"] = content[:200_000]
            else:
                try:
                    entry["content"] = _clone_json(content)
                except (json.JSONDecodeError, TypeError, ValueError):
                    entry["content"] = ""

            tool_calls = msg.get("toolCalls")
            if isinstance(tool_calls, list):
                tc_out: list[dict[str, Any]] = []
                for tc in tool_calls[:200]:
                    if not isinstance(tc, dict):
                        continue
                    try:
                        tc_out.append(_clone_json(tc))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                entry["toolCalls"] = tc_out
            else:
                entry["toolCalls"] = []

            meta = msg.get("meta")
            if isinstance(meta, dict):
                with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                    entry["meta"] = _clone_json(meta)

            messages.append(entry)

        session_id = payload.get("sessionId")
        if session_id is None:
            safe_session_id = None
        else:
            safe_session_id = str(session_id).strip() or None
            if safe_session_id and len(safe_session_id) > 512:
                safe_session_id = safe_session_id[:512]

        chat = {
            "id": resolved_id,
            "title": title,
            "model": str(payload.get("model") or payload.get("profile") or "").strip() or None,
            "messages": messages,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "pinned": bool(payload.get("pinned", False)),
            "sessionId": safe_session_id,
        }

        encoded = json.dumps(chat, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 10_000_000:
            raise web.HTTPBadRequest(text="chat payload too large")
        return chat

    def _read_chat_from_disk(path: Path) -> dict[str, Any] | None:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            raw_id = str(payload.get("id") or "").strip()
            if not raw_id:
                return None
            return _sanitize_chat_payload(payload, chat_id=raw_id)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            log.debug("Skipping unreadable chat file %s: %s", path, e)
            return None

    async def _save_chat_to_disk(chat: dict[str, Any]) -> None:
        payload = json.dumps(chat, ensure_ascii=False, separators=(",", ":"))
        path = _chat_file_for(str(chat.get("id") or ""))
        tmp_path = Path(str(path) + ".tmp")
        async with chat_store_lock:
            try:
                await asyncio.to_thread(chat_store_dir.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(tmp_path.write_text, payload, encoding="utf-8")
                await asyncio.to_thread(tmp_path.replace, path)
            except Exception as e:
                log.error("Failed to save chat to disk: %s", e)
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
                raise

    async def _delete_chat_from_disk(chat_id: str) -> bool:
        path = _chat_file_for(chat_id)
        async with chat_store_lock:
            exists = await asyncio.to_thread(path.exists)
            if not exists:
                return False
            await asyncio.to_thread(path.unlink, missing_ok=True)
        return True

    async def _load_all_chats_from_disk() -> list[dict[str, Any]]:
        chats: list[dict[str, Any]] = []
        async with chat_store_lock:
            paths = await asyncio.to_thread(lambda: list(chat_store_dir.glob("*.json")))
        for path in paths:
            chat = await asyncio.to_thread(_read_chat_from_disk, path)
            if chat is not None:
                chats.append(chat)
        chats.sort(key=lambda c: _safe_int(c.get("updatedAt"), 0), reverse=True)
        return chats

    return {
        "_chat_file_for": _chat_file_for,
        "_sanitize_chat_payload": _sanitize_chat_payload,
        "_read_chat_from_disk": _read_chat_from_disk,
        "_save_chat_to_disk": _save_chat_to_disk,
        "_delete_chat_from_disk": _delete_chat_from_disk,
        "_load_all_chats_from_disk": _load_all_chats_from_disk,
    }
