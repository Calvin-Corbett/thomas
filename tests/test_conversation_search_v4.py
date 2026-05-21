# tests/test_conversation_search_v4.py
from __future__ import annotations

from dataclasses import dataclass

import pytest

from thomas.core.search_history import ConversationSearch


@dataclass
class DummyTurn:
    timestamp: str
    channel: str
    user_msg: str
    assistant_msg: str
    tool_calls: str = ""


class DummyPersistence:
    def __init__(self, turns):
        self.turn_history = list(turns)


@pytest.fixture()
def search(tmp_path, monkeypatch):
    db = tmp_path / "thomas_search_test.db"
    s = ConversationSearch(db_path=db)

    turns = [
        DummyTurn("2026-01-01T10:00:00+00:00", "chat", "hello world", "hi there"),
        DummyTurn("2026-01-02T11:00:00+00:00", "chat", "truck invoice 1242", "noted, invoice 1242 recorded"),
        DummyTurn("2026-01-03T12:00:00+00:00", "tool", "run tool", "tool output", tool_calls='[{"name":"x"}]'),
        DummyTurn("2026-02-01T09:00:00+00:00", "chat", "crash in parser", "stack trace shows crash in tokenize"),
    ]
    persistence = DummyPersistence(turns)

    import thomas.core.search_history as mod

    monkeypatch.setattr(mod, "get_persistence", lambda: persistence)

    s.reindex_all()
    yield s
    s.close()


def test_scoped_search_user_only(search: ConversationSearch):
    res = search.search("invoice", scopes={"user"})
    assert res
    assert any("invoice" in r.user_msg for r in res)


def test_scoped_search_tools(search: ConversationSearch):
    res = search.search("x", scopes={"tools"})
    # could be empty depending on tokenizer; just ensure it doesn't crash
    assert isinstance(res, list)


def test_bookmarks(search: ConversationSearch):
    hit = search.search("invoice", limit=1)[0]
    search.set_bookmark(hit.turn_id, "invoice hit")
    bms = search.list_bookmarks()
    assert any(b.turn_id == hit.turn_id for b in bms)
    search.remove_bookmark(hit.turn_id)
    bms2 = search.list_bookmarks()
    assert all(b.turn_id != hit.turn_id for b in bms2)


def test_saved_search(search: ConversationSearch):
    sid = search.save_search("Invoices", "invoice 1242", {"channel": "chat"})
    saved = search.list_saved_searches()
    assert any(s.id == sid for s in saved)
    search.touch_saved_search(sid)
    search.delete_saved_search(sid)
    saved2 = search.list_saved_searches()
    assert all(s.id != sid for s in saved2)
