"""The chat store, self review and namespace binding reach session files through the sessions slot."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from thomas.chat.session_slot import session_files, sessions
from thomas.server.app_chat_store import _v2_sessions_as_chats
from thomas.server.routes.self_review import _recent_session_excerpts


def _write(store, sid: str, text: str) -> None:
    payload = {
        "session_id": sid,
        "conversation": {"messages": [{"role": "user", "content": text}]},
        "meta": {"session_id": sid},
    }
    store.path_of(sid).write_text(json.dumps(payload), encoding="utf-8")


def test_a_store_and_its_folder_name_the_same_files(tmp_path):
    store = sessions().store_at(tmp_path / "s")
    _write(store, "a", "hello a")
    assert session_files(store) == session_files(tmp_path / "s") == [store.path_of("a")]


def test_history_and_self_review_read_the_same_rows_from_a_store_or_a_folder(tmp_path):
    store = sessions().store_at(tmp_path / "s")
    _write(store, "a", "hello a")
    from_store = _v2_sessions_as_chats(store)
    assert from_store == _v2_sessions_as_chats(tmp_path / "s")
    assert from_store[0]["title"] == "hello a"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    assert _recent_session_excerpts(store, cutoff) == _recent_session_excerpts(tmp_path / "s", cutoff)
    assert "user: hello a" in _recent_session_excerpts(store, cutoff)[0]


@pytest.mark.asyncio
async def test_binding_uses_the_stores_lock_and_file(tmp_path):
    from thomas.chat.session_namespace_binding import bind_surface_namespace

    store = sessions().store_at(tmp_path / "b")
    bound = await bind_surface_namespace(store, "sid", surface_mode="work", context_id="job")
    assert bound is not None
    assert store.path_of("sid").exists()
    assert await bind_surface_namespace(store, "sid", surface_mode="chat", context_id=None) is None
    store.path_of("sid").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        await bind_surface_namespace(store, "sid", surface_mode="work", context_id="job")
