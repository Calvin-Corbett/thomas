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
import sqlite3
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

log = logging.getLogger(__name__)

_HISTORY_CACHE_LIMIT = 512
_HISTORY_CACHE_BYTES = 8 * 1024 * 1024
_history_cache: OrderedDict[Path, tuple[tuple[int, ...], dict[str, Any], int]] = OrderedDict()
_history_cache_lock = Lock()


def _history_fingerprint(path: Path) -> tuple[int, ...]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino


def _history_session_data(path: Path) -> dict[str, Any]:
    """Reuse unchanged disk data; callers construct their own public row objects."""
    key = path.absolute()
    fingerprint = _history_fingerprint(path)
    with _history_cache_lock:
        cached = _history_cache.get(key)
        if cached and cached[0] == fingerprint:
            _history_cache.move_to_end(key)
            return cached[1]
        _history_cache.pop(key, None)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    # Never cache a read spanning a writer's replacement, or an oversized file.
    size = fingerprint[2]
    if size <= _HISTORY_CACHE_BYTES:
        with _history_cache_lock:
            if _history_fingerprint(path) != fingerprint:
                return data
            _history_cache[key] = (fingerprint, data, size)
            _history_cache.move_to_end(key)
            total = sum(entry[2] for entry in _history_cache.values())
            while len(_history_cache) > _HISTORY_CACHE_LIMIT or total > _HISTORY_CACHE_BYTES:
                _, evicted = _history_cache.popitem(last=False)
                total -= evicted[2]
    return data


async def delete_live_chat(app: Any, session_id: str) -> dict[str, Any]:
    """Shared V2 deletion, preserving memory and task-record cleanup receipts."""
    from aiohttp import web

    from thomas.core import task_bot_runtime
    from thomas.server.app_keys import APP_MEMORY
    from thomas.server.chat_attachment_store import forget_chat_originals
    from thomas.server.routes.chat_v2_keys import APP_SESSION_LLM_CACHE, APP_SESSION_STORE
    from thomas.server.routes.chat_v2_support import _evict_session_llm

    cached = (app.get(APP_SESSION_LLM_CACHE) or {}).get(session_id)
    if cached is not None and cached.lock.locked():
        raise web.HTTPConflict(text="Stop the active reply before deleting this chat.")
    store = app.get(APP_SESSION_STORE)
    deleted = await store.delete(session_id) if store is not None else False
    with _history_cache_lock:
        for key, (_, data, _) in list(_history_cache.items()):
            if data.get("session_id") == session_id:
                del _history_cache[key]
    await _evict_session_llm(app, session_id)
    await asyncio.to_thread(forget_chat_originals, session_id)
    memory_purge: dict[str, Any] = {"completed": False, "forgotten": False}
    forget_thread = getattr(app.get(APP_MEMORY), "forget_thread", None)
    if callable(forget_thread):
        try:
            memory_purge = {"completed": True, **dict(await asyncio.to_thread(forget_thread, session_id))}
        except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
            memory_purge = {"completed": False, "forgotten": False, "error": type(exc).__name__}
    tasks_removed = 0
    try:
        tasks_removed = await asyncio.to_thread(task_bot_runtime.delete_session_executions, session_id)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        log.warning("could not remove task records for deleted session %s: %s", session_id, exc)
    return {
        "deleted": deleted,
        "session_id": session_id,
        "memory_purge": memory_purge,
        "task_records_removed": tasks_removed,
    }


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
        async with chat_store_lock:
            paths = await asyncio.to_thread(lambda: list(chat_store_dir.glob("*.json")))

        def read_batch() -> list[dict[str, Any]]:
            chats = [chat for path in paths if (chat := _read_chat_from_disk(path)) is not None]
            chats.sort(key=lambda c: _safe_int(c.get("updatedAt"), 0), reverse=True)
            return chats

        return await asyncio.to_thread(read_batch)

    return {
        "_chat_file_for": _chat_file_for,
        "_sanitize_chat_payload": _sanitize_chat_payload,
        "_read_chat_from_disk": _read_chat_from_disk,
        "_save_chat_to_disk": _save_chat_to_disk,
        "_delete_chat_from_disk": _delete_chat_from_disk,
        "_load_all_chats_from_disk": _load_all_chats_from_disk,
    }


def _v2_sessions_as_chats(
    sessions_dir: Path,
    *,
    limit: int = 300,
    surface_mode: str = "",
    context_id: str = "",
) -> list[dict[str, Any]]:
    """Convert the LIVE v2 session store (``.thomas/sessions_v2/chat_*.json`` — where
    every chat conducted through /api/v2/chat is saved) into the sidebar's chat-list
    schema. GET /api/chats historically read ONLY the legacy ``.thomas/chats`` directory
    (written by the old SPA's PUT /api/chats), which the current chat UI never writes —
    so brand-new chats never showed up in Recent (no entry, no date). This bridges the
    two so real, current chats appear with their dates. (chat history fix, 2026-06-28)"""
    out: list[dict[str, Any]] = []
    try:
        files = list(sessions_dir.glob("chat_*.json"))
    except OSError:
        return out

    # Deleted histories are not served from memory, and release their cache data.
    present = {path.absolute() for path in files}
    directory = sessions_dir.absolute()
    with _history_cache_lock:
        for key in list(_history_cache):
            if key.parent == directory and key not in present:
                del _history_cache[key]

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    files.sort(key=_mtime, reverse=True)
    result_limit = max(1, int(limit))
    for path in files:
        try:
            data = _history_session_data(path)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        sid = str(data.get("session_id") or "").strip()
        if not sid:
            continue
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        stored_surface = str(meta.get("surface_mode") or "chat").strip().lower()
        stored_context = str(meta.get("context_id") or "").strip()
        if surface_mode and stored_surface != surface_mode:
            continue
        if context_id and stored_context != context_id:
            continue
        conv = data.get("conversation") if isinstance(data.get("conversation"), dict) else {}
        msgs: list[dict[str, Any]] = []
        for msg in conv.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "")
            content = msg.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                mapped = {"role": role, "content": content}
                metadata = msg.get("metadata")
                if isinstance(metadata, dict):
                    mapped["metadata"] = metadata
                msgs.append(mapped)
        if not msgs:
            continue  # empty / system-only session — nothing to show in the sidebar
        first_user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        title = (first_user.strip().splitlines()[0][:60] if first_user.strip() else "New chat") or "New chat"
        saved_at = data.get("saved_at")
        updated_ms = int(float(saved_at) * 1000) if isinstance(saved_at, (int, float)) else int(_mtime(path) * 1000)
        out.append(
            {
                "id": sid,
                "sessionId": sid,
                "title": title,
                "surfaceMode": stored_surface,
                "contextId": stored_context,
                "model": str(meta.get("model_id") or ""),
                "messages": msgs,
                "createdAt": updated_ms,
                "updatedAt": updated_ms,
                "pinned": False,
            }
        )
        if len(out) >= result_limit:
            break
    return out
