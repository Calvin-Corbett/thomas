import json
from collections import OrderedDict
from pathlib import Path
from unittest.mock import patch

from thomas.server import app_chat_store as history


def write_session(path, text, mode="chat", context=""):
    path.write_text(
        json.dumps(
            {
                "session_id": path.stem,
                "meta": {"surface_mode": mode, "context_id": context},
                "conversation": {"messages": [{"role": "user", "content": text}]},
            }
        ),
        encoding="utf-8",
    )


def test_unchanged_sessions_are_read_once_and_rows_are_not_shared(tmp_path):
    path = tmp_path / "chat_one.json"
    write_session(path, "Original question")
    original = Path.read_text
    reads = []

    def read(file, *args, **kwargs):
        reads.append(file)
        return original(file, *args, **kwargs)

    with patch.object(Path, "read_text", read):
        first = history._v2_sessions_as_chats(tmp_path)
        first[0]["messages"][0]["content"] = "A caller changed its copy"
        second = history._v2_sessions_as_chats(tmp_path)
    assert second[0]["messages"][0]["content"] == "Original question"
    assert reads == [path]


def test_replacement_deletion_corruption_and_new_files_are_visible(tmp_path):
    path = tmp_path / "chat_one.json"
    write_session(path, "Original")
    assert history._v2_sessions_as_chats(tmp_path)[0]["title"] == "Original"
    replacement = tmp_path / "replacement.json"
    write_session(replacement, "Edited")
    replacement.replace(path)
    assert history._v2_sessions_as_chats(tmp_path)[0]["title"] == "Edited"
    path.write_text("{broken", encoding="utf-8")
    assert history._v2_sessions_as_chats(tmp_path) == []
    write_session(path, "Recovered")
    assert history._v2_sessions_as_chats(tmp_path)[0]["title"] == "Recovered"
    path.unlink()
    assert history._v2_sessions_as_chats(tmp_path) == []
    write_session(tmp_path / "chat_new.json", "New conversation")
    assert history._v2_sessions_as_chats(tmp_path)[0]["title"] == "New conversation"


def test_cached_histories_stay_separate_by_directory_mode_and_context(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    write_session(tmp_path / "chat_same.json", "Chat")
    write_session(other / "chat_same.json", "Work", "work", "app:job")
    assert history._v2_sessions_as_chats(tmp_path)[0]["title"] == "Chat"
    assert history._v2_sessions_as_chats(other, surface_mode="chat") == []
    assert history._v2_sessions_as_chats(other, surface_mode="work", context_id="wrong") == []
    assert history._v2_sessions_as_chats(other, surface_mode="work", context_id="app:job")[0]["title"] == "Work"


def test_history_cache_is_bounded_and_does_not_drop_large_histories(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_history_cache", OrderedDict())
    monkeypatch.setattr(history, "_HISTORY_CACHE_LIMIT", 2)
    for index in range(3):
        write_session(tmp_path / f"chat_{index}.json", f"Question {index}")
    assert len(history._v2_sessions_as_chats(tmp_path)) == 3
    assert len(history._history_cache) == 2
    monkeypatch.setattr(history, "_HISTORY_CACHE_BYTES", 1)
    history._history_cache.clear()
    assert len(history._v2_sessions_as_chats(tmp_path)) == 3
    assert not history._history_cache
