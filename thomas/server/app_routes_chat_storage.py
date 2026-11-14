"""The chat storage handlers (list, put, delete), built for ``app_routes_init``.

They merge the legacy ``.thomas/chats`` store with the live sessions store and
lived as nested functions inside ``_setup_routes_and_handlers``; the
initializer still registers them by name and its run-store janitor keeps its
own hooks, so this returns the three handlers in a dict. Third inner cut.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas.chat.session_slot import sessions
from thomas.core.config import AppConfig
from thomas.server.routes.chat_surface_namespace import normalize_workspace_context_id

from .app_chat_store import _v2_sessions_as_chats, delete_live_chat


def build_chat_storage_handlers(
    config: AppConfig,
    *,
    require_api_access: Callable[..., Any],
    read_json: Callable[..., Any],
    is_json_content_type: Callable[..., Any],
    load_all_chats_from_disk: Callable[..., Any],
    save_chat_to_disk: Callable[..., Any],
    delete_chat_from_disk: Callable[..., Any],
    sanitize_chat_payload: Callable[..., Any],
) -> dict[str, Callable[..., Any]]:
    """Return api_chats, api_chat_put and api_chat_delete keyed by name."""
    _require_api_access = require_api_access
    _read_json = read_json
    _is_json_content_type = is_json_content_type
    _load_all_chats_from_disk = load_all_chats_from_disk
    _save_chat_to_disk = save_chat_to_disk
    _delete_chat_from_disk = delete_chat_from_disk
    _sanitize_chat_payload = sanitize_chat_payload

    async def api_chats(request: web.Request) -> web.Response:
        """List all chats from disk storage.

        Merges the legacy ``.thomas/chats`` store (old SPA's PUT /api/chats) with the
        LIVE ``.thomas/sessions_v2`` store (every chat from the current /api/v2/chat
        flow). Before this merge the sidebar only saw the legacy store, so new chats
        never appeared in Recent. Dedup by id; the newer ``updatedAt`` wins.
        """
        _require_api_access(request)
        requested_surface = str(request.query.get("mode") or "").strip().lower()
        requested_context = str(request.query.get("context_id") or "").strip()
        if requested_surface and requested_surface not in {"chat", "work", "workspace"}:
            raise web.HTTPBadRequest(text="mode must be chat, work, or workspace")
        if requested_surface == "workspace":
            if not requested_context:
                raise web.HTTPBadRequest(text="context_id is required for workspace histories")
            try:
                requested_context = normalize_workspace_context_id(requested_context)
            except ValueError as exc:
                raise web.HTTPBadRequest(text=str(exc)) from exc
        store = sessions().store(config.memory.root_path)
        legacy, live = await asyncio.gather(
            _load_all_chats_from_disk(),
            asyncio.to_thread(
                _v2_sessions_as_chats,
                store,
                surface_mode=requested_surface,
                context_id=requested_context,
            ),
        )

        def _ms(chat: dict[str, Any]) -> int:
            try:
                return int(chat.get("updatedAt") or 0)
            except (TypeError, ValueError):
                return 0

        by_id: dict[str, dict[str, Any]] = {}
        for chat in [*legacy, *live]:
            cid = str(chat.get("id") or chat.get("sessionId") or "").strip()
            if not cid:
                continue
            surface = str(chat.get("surfaceMode") or chat.get("surface_mode") or "chat").strip().lower()
            context_id = str(chat.get("contextId") or chat.get("context_id") or "").strip()
            if requested_surface and surface != requested_surface:
                continue
            if requested_context and context_id != requested_context:
                continue
            # Preserve the exact legacy response contract for callers that never
            # opted into namespaced histories. V2 rows already carry these keys.
            row = dict(chat)
            if "surfaceMode" in chat or "surface_mode" in chat:
                row["surfaceMode"] = surface
            if "contextId" in chat or "context_id" in chat:
                row["contextId"] = context_id
            prev = by_id.get(cid)
            if prev is None or _ms(row) >= _ms(prev):
                by_id[cid] = row
        chats = sorted(by_id.values(), key=_ms, reverse=True)
        return web.json_response({"chats": chats})

    async def api_chat_put(request: web.Request) -> web.Response:
        """Save or update a chat."""
        _require_api_access(request)
        if not _is_json_content_type(request):
            raise web.HTTPBadRequest(text="Content-Type must be application/json")

        payload = await _read_json(request)
        chat = _sanitize_chat_payload(payload)

        # If the URL specifies a chat_id, it must match the payload id (prevents
        # accidental cross-chat overwrites). Returns 400 on mismatch.
        url_chat_id = request.match_info.get("chat_id", "").strip()
        payload_chat_id = str(chat.get("id") or "").strip()
        if url_chat_id and payload_chat_id and url_chat_id != payload_chat_id:
            raise web.HTTPBadRequest(text=f"chat id mismatch: URL='{url_chat_id}' payload='{payload_chat_id}'")

        await _save_chat_to_disk(chat)
        return web.json_response({"ok": True, "chat": chat})

    async def api_chat_delete(request: web.Request) -> web.Response:
        """Delete a chat."""
        _require_api_access(request)
        chat_id = request.match_info.get("chat_id", "")
        if not chat_id:
            raise web.HTTPBadRequest(text="missing chat_id")

        # Delete the compatibility record first. Optional V2 route modules are
        # deliberately unavailable in legacy-only app configurations, but that
        # must not turn a successful legacy deletion into a 500 response.
        legacy_deleted = await _delete_chat_from_disk(chat_id)
        try:
            live_result = await delete_live_chat(request.app, chat_id)
        except ModuleNotFoundError:
            # V2 chat storage is optional in compatibility-only app setups. Treat
            # its unavailable lazy dependency as an empty V2 store; the legacy
            # record above remains authoritative for both success and 404.
            live_result = {"deleted": False, "memory_purge": {"completed": False}, "task_records_removed": 0}
        deleted = live_result["deleted"] or legacy_deleted
        if not deleted:
            raise web.HTTPNotFound(text=f"chat {chat_id} not found")
        # Tests expect 200 with a small JSON ack (was 204 no-content).
        return web.json_response({**live_result, "ok": True, "deleted": chat_id})

    return {"api_chats": api_chats, "api_chat_put": api_chat_put, "api_chat_delete": api_chat_delete}
