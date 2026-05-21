"""
Thomas - Preferences API (FastAPI)

Routes
- GET   /api/preferences
- PATCH /api/preferences
- GET   /settings
- GET   /js/settings.js

Integration:
    from thomas.preferences.api import router as preferences_router
    app.include_router(preferences_router)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from thomas.preferences.store import PreferencesPatch, PreferencesResponse, PreferencesStore, get_db_path

router = APIRouter(tags=["preferences"])


@lru_cache(maxsize=8)
def _store_for_path(db_path: str) -> PreferencesStore:
    return PreferencesStore(db_path=db_path)


def get_store() -> PreferencesStore:
    # Cache per DB path so multi-instance setups and tests don't reuse stale stores.
    return _store_for_path(get_db_path())


def get_user_id(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> str:
    # Thomas is often single-user. Support header-based segmentation.
    return (x_user_id or "default").strip() or "default"


def _web_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "server" / "web"


@router.get("/api/preferences", response_model=PreferencesResponse)
def get_preferences(
    thread_id: str | None = Query(default=None, description="Optional thread identifier for per-thread memory toggle."),
    store: PreferencesStore = Depends(get_store),
    user_id: str = Depends(get_user_id),
) -> PreferencesResponse:
    return store.get(user_id=user_id, thread_id=thread_id)


@router.patch("/api/preferences", response_model=PreferencesResponse)
def patch_preferences(
    patch: PreferencesPatch,
    thread_id: str | None = Query(default=None, description="Optional thread identifier for per-thread memory toggle."),
    store: PreferencesStore = Depends(get_store),
    user_id: str = Depends(get_user_id),
) -> PreferencesResponse:
    try:
        return store.patch(patch=patch, user_id=user_id, thread_id=thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/settings")
def settings_page() -> FileResponse:
    p = _web_dir() / "settings.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="settings.html not found")
    return FileResponse(p, media_type="text/html; charset=utf-8")


@router.get("/js/settings.js")
def settings_js() -> FileResponse:
    p = _web_dir() / "js" / "settings.js"
    if not p.exists():
        raise HTTPException(status_code=404, detail="settings.js not found")
    return FileResponse(p, media_type="application/javascript; charset=utf-8")
