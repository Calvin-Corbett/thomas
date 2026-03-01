"""aiohttp routes for conversation search (FTS5 full-text search API).

Endpoints cover full-text search, autocomplete, context retrieval,
channel listing, bookmarks, saved searches, and index management.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Dict

from aiohttp import web

from thomas.core.search_history import get_search

# Type alias matching the pattern used by spend/goals routes.
RequireAccessFn = Callable[[web.Request], None]


def register_search_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
) -> None:
    """Register all /api/search/* routes on *app*."""

    # ── helpers ──────────────────────────────────────────────

    def _qp(request: web.Request, key: str, default: str | None = None) -> str | None:
        """Return a query-parameter or *default*."""
        v = request.rel_url.query.get(key)
        if v in (None, ""):
            return default
        return v

    def _qp_int(request: web.Request, key: str, default: int) -> int:
        v = _qp(request, key)
        if v is None:
            return default
        try:
            return int(v)
        except (ValueError, TypeError):
            return default

    def _qp_bool(request: web.Request, key: str) -> bool | None:
        v = _qp(request, key)
        if v is None:
            return None
        normalized = v.strip().lower()
        if normalized in ("1", "true", "yes"):
            return True
        if normalized in ("0", "false", "no"):
            return False
        raise web.HTTPBadRequest(text=f"invalid boolean value for '{key}'")

    async def _read_json(request: web.Request) -> Dict[str, Any]:
        try:
            data = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text=f"invalid json: {exc}")
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text="json body must be an object")
        return data

    # ── GET /api/search ──────────────────────────────────────

    async def api_search(request: web.Request) -> web.Response:
        require_api_access(request)
        q = (_qp(request, "q") or "").strip()
        if not q:
            raise web.HTTPBadRequest(text="query parameter 'q' is required")

        limit = max(1, min(_qp_int(request, "limit", 20), 200))
        offset = max(0, min(_qp_int(request, "offset", 0), 10000))
        channel = _qp(request, "channel")
        since = _qp(request, "since")
        before = _qp(request, "before")
        has_tools = _qp_bool(request, "has_tools")
        sort = ((_qp(request, "sort", "relevance") or "relevance").strip().lower())
        if sort not in {"relevance", "newest"}:
            raise web.HTTPBadRequest(text="query parameter 'sort' must be one of: relevance, newest")
        scope_raw = _qp(request, "scope", "all") or "all"
        scopes = {s.strip().lower() for s in scope_raw.split(",") if s.strip()} or {"all"}
        saved_id = _qp_int(request, "saved_id", -1)

        search = get_search()
        search.record_query(q)

        results = search.search(
            query=q,
            limit=limit,
            offset=offset,
            channel=channel,
            since=since,
            before=before,
            has_tool_calls=has_tools,
            sort=sort,
            scopes=scopes,
        )

        if saved_id >= 0:
            try:
                search.touch_saved_search(saved_id)
            except Exception:
                pass

        return web.json_response([asdict(r) for r in results])

    # ── GET /api/search/suggest ──────────────────────────────

    async def api_suggest(request: web.Request) -> web.Response:
        require_api_access(request)
        q = (_qp(request, "q") or "").strip()
        if not q:
            raise web.HTTPBadRequest(text="query parameter 'q' is required")
        return web.json_response(get_search().suggest(q))

    # ── GET /api/search/context ──────────────────────────────

    async def api_context(request: web.Request) -> web.Response:
        require_api_access(request)
        turn_id = (_qp(request, "turn_id") or "").strip()
        if not turn_id:
            raise web.HTTPBadRequest(text="query parameter 'turn_id' is required")
        window = max(0, min(_qp_int(request, "window", 2), 25))
        ctx = get_search().get_context(turn_id=turn_id, window=window)
        return web.json_response([asdict(c) for c in ctx])

    # ── GET /api/search/channels ─────────────────────────────

    async def api_channels(request: web.Request) -> web.Response:
        require_api_access(request)
        return web.json_response(get_search().list_channels())

    # ── GET /api/search/status ───────────────────────────────

    async def api_status(request: web.Request) -> web.Response:
        require_api_access(request)
        return web.json_response(get_search().status())

    # ── POST /api/search/reindex ─────────────────────────────

    async def api_reindex(request: web.Request) -> web.Response:
        require_api_access(request)
        s = get_search()
        s.reindex_all()
        return web.json_response(s.status())

    # ── Bookmarks ────────────────────────────────────────────

    async def api_list_bookmarks(request: web.Request) -> web.Response:
        require_api_access(request)
        bms = get_search().list_bookmarks()
        return web.json_response([asdict(b) for b in bms])

    async def api_set_bookmark(request: web.Request) -> web.Response:
        require_api_access(request)
        data = await _read_json(request)
        turn_id = str(data.get("turn_id") or "").strip()
        if not turn_id:
            raise web.HTTPBadRequest(text="'turn_id' is required")
        label = str(data.get("label") or "")
        get_search().set_bookmark(turn_id, label)
        return web.json_response({"ok": True})

    async def api_remove_bookmark(request: web.Request) -> web.Response:
        require_api_access(request)
        turn_id = request.match_info["turn_id"]
        get_search().remove_bookmark(turn_id)
        return web.json_response({"ok": True})

    # ── Saved Searches ───────────────────────────────────────

    async def api_list_saved(request: web.Request) -> web.Response:
        require_api_access(request)
        ss = get_search().list_saved_searches()
        return web.json_response([asdict(s) for s in ss])

    async def api_save_search(request: web.Request) -> web.Response:
        require_api_access(request)
        data = await _read_json(request)
        name = str(data.get("name") or "").strip()
        query = str(data.get("query") or "").strip()
        if not query:
            raise web.HTTPBadRequest(text="'query' is required")
        filters = data.get("filters") or {}
        if not isinstance(filters, dict):
            filters = {}
        sid = get_search().save_search(name, query, filters)
        return web.json_response({"ok": True, "id": sid})

    async def api_delete_saved(request: web.Request) -> web.Response:
        require_api_access(request)
        sid_raw = request.match_info["sid"]
        try:
            sid = int(sid_raw)
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="invalid saved search id")
        get_search().delete_saved_search(sid)
        return web.json_response({"ok": True})

    # ── route registration ───────────────────────────────────

    app.router.add_get("/api/search", api_search)
    app.router.add_get("/api/search/suggest", api_suggest)
    app.router.add_get("/api/search/context", api_context)
    app.router.add_get("/api/search/channels", api_channels)
    app.router.add_get("/api/search/status", api_status)
    app.router.add_post("/api/search/reindex", api_reindex)
    app.router.add_get("/api/search/bookmarks", api_list_bookmarks)
    app.router.add_post("/api/search/bookmarks", api_set_bookmark)
    app.router.add_delete("/api/search/bookmarks/{turn_id}", api_remove_bookmark)
    app.router.add_get("/api/search/saved", api_list_saved)
    app.router.add_post("/api/search/saved", api_save_search)
    app.router.add_delete("/api/search/saved/{sid}", api_delete_saved)
