# thomas/server/routes/search.py
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from thomas.core.search_history import get_search


router = APIRouter(tags=["search"])


class SearchResultModel(BaseModel):
    turn_id: str
    turn_pos: int
    ts: str
    channel: str
    user_msg: str
    user_snippet: str
    assistant_snippet: str
    assistant_snippet_plain: str
    rank: float
    score: float


class TurnContextModel(BaseModel):
    turn_id: str
    turn_pos: int
    ts: str
    channel: str
    user_msg: str
    assistant_msg: str
    tool_calls: str


class SearchStatusModel(BaseModel):
    db_path: str
    indexed_rows: int
    last_indexed_pos: int
    last_optimize_at_pos: int
    db_size_bytes: int
    schema_version: str
    bookmarks: int
    saved_searches: int


class BookmarkModel(BaseModel):
    turn_id: str
    label: str = ""
    created_ts: str | None = None


class SavedSearchModel(BaseModel):
    id: int
    name: str
    query: str
    filters_json: str
    created_ts: str
    last_used_ts: str
    use_count: int


class SaveSearchRequest(BaseModel):
    name: str
    query: str
    filters: dict = {}


@router.get("/api/search", response_model=list[SearchResultModel])
def api_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    channel: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="YYYY-MM-DD or ISO"),
    before: Optional[str] = Query(None, description="YYYY-MM-DD or ISO"),
    has_tools: Optional[bool] = Query(None),
    sort: str = Query("relevance", description="relevance | newest"),
    scope: str = Query("all", description="Comma list: all,user,assistant,tools"),
    saved_id: Optional[int] = Query(None, description="If provided, increments saved search use_count"),
):
    search = get_search()
    search.record_query(q)

    scopes = set([s.strip().lower() for s in (scope or "all").split(",") if s.strip()])
    if not scopes:
        scopes = {"all"}

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
    if saved_id is not None:
        try:
            search.touch_saved_search(int(saved_id))
        except Exception:
            pass

    return [SearchResultModel(**r.__dict__) for r in results]


@router.get("/api/search/suggest", response_model=list[str])
def api_suggest(q: str = Query(..., min_length=1)):
    return get_search().suggest(q)


@router.get("/api/search/context", response_model=list[TurnContextModel])
def api_context(turn_id: str = Query(..., min_length=1), window: int = Query(2, ge=0, le=25)):
    ctx = get_search().get_context(turn_id=turn_id, window=window)
    return [TurnContextModel(**c.__dict__) for c in ctx]


@router.get("/api/search/channels", response_model=list[str])
def api_channels():
    return get_search().list_channels()


@router.get("/api/search/status", response_model=SearchStatusModel)
def api_status():
    return SearchStatusModel(**get_search().status())


@router.post("/api/search/reindex", response_model=SearchStatusModel)
def api_reindex():
    s = get_search()
    s.reindex_all()
    return SearchStatusModel(**s.status())


# -----------------------
# Bookmarks
# -----------------------
@router.get("/api/search/bookmarks", response_model=list[BookmarkModel])
def api_list_bookmarks():
    bms = get_search().list_bookmarks()
    return [BookmarkModel(turn_id=b.turn_id, label=b.label, created_ts=b.created_ts) for b in bms]


@router.post("/api/search/bookmarks", response_model=dict)
def api_set_bookmark(req: BookmarkModel):
    s = get_search()
    s.set_bookmark(req.turn_id, req.label or "")
    return {"ok": True}


@router.delete("/api/search/bookmarks/{turn_id}", response_model=dict)
def api_remove_bookmark(turn_id: str):
    s = get_search()
    s.remove_bookmark(turn_id)
    return {"ok": True}


# -----------------------
# Saved Searches
# -----------------------
@router.get("/api/search/saved", response_model=list[SavedSearchModel])
def api_list_saved():
    ss = get_search().list_saved_searches()
    return [SavedSearchModel(**x.__dict__) for x in ss]


@router.post("/api/search/saved", response_model=dict)
def api_save_search(req: SaveSearchRequest):
    s = get_search()
    sid = s.save_search(req.name, req.query, req.filters or {})
    return {"ok": True, "id": sid}


@router.delete("/api/search/saved/{sid}", response_model=dict)
def api_delete_saved(sid: int):
    get_search().delete_saved_search(int(sid))
    return {"ok": True}
