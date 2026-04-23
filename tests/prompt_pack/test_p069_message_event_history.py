import argparse
import json
from pathlib import Path

import pytest

from thomas.messages.p069_message_event_history import (
    MessageEventHistoryConfigError,
    MessageEventHistoryInvalidInputError,
    MessageEventHistoryRequest,
    append_message_event,
    get_message_event_history,
    response_to_json,
)

from thomas.cli.commands.messages import p069_message_event_history as cli_mod


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def test_append_and_read_roundtrip(tmp_path: Path) -> None:
    store = tmp_path / "events.jsonl"

    append_message_event(
        {"messageId": "abc", "status": "sent", "timestamp": "2025-01-01T00:00:00Z"},
        store_path=str(store),
    )

    resp = get_message_event_history(MessageEventHistoryRequest(message_id="abc", store_path=str(store), limit=10))
    payload = response_to_json(resp)
    assert payload["message_id"] == "abc"
    assert payload["events"][0]["event_type"] == "sent"
    assert payload["events"][0]["source_path"] is not None


def test_event_history_reads_and_sorts(tmp_path: Path) -> None:
    store = tmp_path / "events.jsonl"

    # Mix normalized and raw-ish events, out of order.
    _write_jsonl(
        store,
        [
            {"schema": "thomas.messages.event.v1", "message_id": "abc", "event_type": "delivered", "occurred_at": "2025-01-02T03:04:05Z", "raw": {"status": "delivered"}},
            {"messageId": "abc", "status": "sent", "timestamp": "2025-01-01T00:00:01Z"},
            {"schema": "thomas.messages.event.v1", "message_id": "def", "event_type": "sent", "occurred_at": "2025-01-01T00:00:00Z", "raw": {}},
            {"schema": "thomas.messages.event.v1", "message_id": "abc", "event_type": "queued", "occurred_at": "2024-12-31T23:59:59Z", "raw": {"status": "queued"}},
        ],
    )

    resp = get_message_event_history(MessageEventHistoryRequest(message_id="abc", store_path=str(store), limit=10))
    payload = response_to_json(resp)

    assert payload["message_id"] == "abc"
    assert [e["event_type"] for e in payload["events"]] == ["queued", "sent", "delivered"]


def test_event_history_discovers_default_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Place file in the default discovery location: <state>/messages/events.jsonl
    store = tmp_path / "messages" / "events.jsonl"
    _write_jsonl(
        store,
        [
            {"schema": "thomas.messages.event.v1", "message_id": "abc", "event_type": "sent", "occurred_at": "2025-01-01T00:00:00Z", "raw": {"status": "sent"}},
        ],
    )
    monkeypatch.setenv("THOMAS_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("THOMAS_MESSAGE_EVENTS_PATH", raising=False)

    resp = get_message_event_history(MessageEventHistoryRequest(message_id="abc"))
    payload = response_to_json(resp)

    assert payload["message_id"] == "abc"
    assert payload["events"][0]["event_type"] == "sent"
    assert str(store) in payload["source_paths"]


def test_event_history_invalid_input_raises() -> None:
    with pytest.raises(MessageEventHistoryInvalidInputError):
        get_message_event_history(MessageEventHistoryRequest(message_id="  ", store_path="does-not-matter.jsonl"))


def test_event_history_missing_config_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("THOMAS_MESSAGE_EVENTS_PATH", raising=False)

    with pytest.raises(MessageEventHistoryConfigError) as excinfo:
        get_message_event_history(MessageEventHistoryRequest(message_id="abc"))

    assert excinfo.value.code == "messages.event_history.missing_config"


def test_cli_json_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "events.jsonl"
    _write_jsonl(
        store,
        [
            {"schema": "thomas.messages.event.v1", "message_id": "abc", "event_type": "sent", "occurred_at": "2025-01-01T00:00:00Z", "raw": {"status": "sent"}},
        ],
    )

    args = argparse.Namespace(
        message_id="abc",
        limit=200,
        store_path=str(store),
        state_dir=None,
        as_json=True,
    )
    exit_code = cli_mod.run(args)
    out = capsys.readouterr().out.strip()

    assert exit_code == 0
    parsed = json.loads(out)
    assert parsed["ok"] is True
    assert parsed["message_id"] == "abc"
    assert parsed["events"][0]["event_type"] == "sent"


def test_cli_json_failure_has_code(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(
        message_id="",
        limit=200,
        store_path=None,
        state_dir=None,
        as_json=True,
    )
    exit_code = cli_mod.run(args)
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)

    assert exit_code != 0
    assert parsed["ok"] is False
    assert parsed["error"]["code"] == "messages.event_history.invalid_input"
