from __future__ import annotations

from pathlib import Path

import pytest

from thomas.messages.p053_message_schema_and_persistence_refactor import (
    MESSAGE_INGEST_JSON_SCHEMA,
    MessageConfigError,
    MessageStore,
    MessageStoreConfig,
    MessageValidationError,
    ingest_and_persist,
    ingest_and_persist_safe,
    resolve_store_path,
)


def test_success_persists_and_can_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "msg.sqlite3"
    monkeypatch.setenv("THOMAS_MESSAGE_STORE", str(db_path))

    result = ingest_and_persist({"text": "hello", "channel": "ops", "sender": "calvin"})
    assert result.record.text == "hello"
    assert result.record.channel == "ops"
    assert result.record.sender == "calvin"
    assert Path(result.store_path) == db_path
    assert result.inserted is True

    store = MessageStore(MessageStoreConfig(db_path=db_path))
    rows = store.list(limit=10)
    assert len(rows) == 1
    assert rows[0].text == "hello"
    assert rows[0].channel == "ops"


def test_idempotent_message_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "msg.sqlite3"
    monkeypatch.setenv("THOMAS_MESSAGE_STORE", str(db_path))

    payload = {"message_id": "abc-123", "text": "hello"}
    r1 = ingest_and_persist(payload)
    assert r1.inserted is True
    r2 = ingest_and_persist(payload)
    assert r2.inserted is False
    assert r1.record.message_id == r2.record.message_id == "abc-123"

    store = MessageStore(MessageStoreConfig(db_path=db_path))
    assert len(store.list(limit=10)) == 1


def test_metadata_merging_and_timestamp_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "msg.sqlite3"
    monkeypatch.setenv("THOMAS_MESSAGE_STORE", str(db_path))

    payload = {
        "text": "hi",
        "created_at": "2025-01-02T03:04:05Z",
        "metadata": {"a": 1, "x": "explicit"},
        "x": "leftover",
        "y": 2,
    }
    res = ingest_and_persist(payload)
    assert res.record.created_at.isoformat().startswith("2025-01-02T03:04:05")
    # explicit metadata wins
    assert res.record.metadata["x"] == "explicit"
    assert res.record.metadata["y"] == 2
    assert res.record.metadata["a"] == 1


def test_invalid_input_missing_text_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "msg.sqlite3"
    monkeypatch.setenv("THOMAS_MESSAGE_STORE", str(db_path))
    with pytest.raises(MessageValidationError) as ei:
        ingest_and_persist({"channel": "x"})
    assert ei.value.code == "invalid_input"


def test_missing_config_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_MESSAGE_STORE", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGES_DB", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGE_DB", raising=False)
    monkeypatch.delenv("THOMAS_DATA_DIR", raising=False)
    monkeypatch.delenv("THOMAS_HOME", raising=False)

    with pytest.raises(MessageConfigError) as ei:
        resolve_store_path()
    assert ei.value.code == "missing_config"


def test_invalid_store_path_directory_is_error(tmp_path: Path) -> None:
    store_dir = tmp_path / "store_dir"
    store_dir.mkdir()
    safe = ingest_and_persist_safe({"text": "hi"}, store_path=str(store_dir))
    assert safe["ok"] is False
    assert safe["error"]["code"] == "invalid_store_path"


def test_json_schema_is_machine_readable() -> None:
    assert MESSAGE_INGEST_JSON_SCHEMA["type"] == "object"
    assert "text" in MESSAGE_INGEST_JSON_SCHEMA["properties"]
    assert "text" in MESSAGE_INGEST_JSON_SCHEMA["required"]
