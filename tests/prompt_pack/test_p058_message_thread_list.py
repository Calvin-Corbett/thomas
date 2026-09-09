import json

import pytest
from click.testing import CliRunner

from thomas.cli.commands.messages.p058_message_thread_list import COMMAND
from thomas.messages.p058_message_thread_list import (
    JsonlMessageStoreBackend,
    MessageThreadListConfigError,
    MessageThreadListExternalError,
    MessageThreadListInvalidInput,
    MessageThreadListRequest,
    MessageThreadListResponse,
    MessageThreadSummary,
    list_message_threads,
)


class _StubBackend:
    def __init__(self, response: MessageThreadListResponse | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc

    def list_threads(self, request: MessageThreadListRequest) -> MessageThreadListResponse:
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def test_list_message_threads_success_with_backend():
    backend = _StubBackend(
        response=MessageThreadListResponse(
            threads=[
                MessageThreadSummary(thread_id="t1", channel_id="c1", title="A", message_count=2),
                MessageThreadSummary(thread_id="t2", channel_id="c1", title="B", message_count=1),
            ],
            next_cursor="2",
        )
    )

    req = MessageThreadListRequest(channel_id="c1", limit=2)
    out = list_message_threads(req, backend=backend)

    assert out.next_cursor == "2"
    assert [t.thread_id for t in out.threads] == ["t1", "t2"]


def test_list_message_threads_invalid_limit_raises():
    req = MessageThreadListRequest(limit=0)
    with pytest.raises(MessageThreadListInvalidInput) as excinfo:
        list_message_threads(req, backend=_StubBackend(response=MessageThreadListResponse()))

    assert excinfo.value.code == "invalid_input"
    assert "limit" in excinfo.value.message


def test_list_message_threads_missing_backend_config_raises(monkeypatch):
    monkeypatch.delenv("THOMAS_MESSAGE_STORE_PATH", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGES_STORE_PATH", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGE_THREAD_STORE_PATH", raising=False)

    req = MessageThreadListRequest(limit=1)
    with pytest.raises(MessageThreadListConfigError) as excinfo:
        list_message_threads(req, backend=None, config={})

    assert excinfo.value.code == "missing_config"


def test_list_message_threads_backend_failure_is_wrapped():
    req = MessageThreadListRequest(limit=1)
    backend = _StubBackend(exc=RuntimeError("boom"))

    with pytest.raises(MessageThreadListExternalError) as excinfo:
        list_message_threads(req, backend=backend)

    assert excinfo.value.code == "external_failure"


def test_jsonl_backend_paginates_and_sorts(tmp_path):
    store = tmp_path / "messages.jsonl"
    store.write_text(
        "\n".join(
            [
                json.dumps({"thread_id": "t1", "channel_id": "c1", "timestamp": "2024-01-01T00:00:00Z"}),
                json.dumps({"thread_id": "t2", "channel_id": "c1", "timestamp": "2024-01-02T00:00:00Z"}),
                json.dumps({"thread_id": "t1", "channel_id": "c1", "timestamp": "2024-01-03T00:00:00Z"}),
                json.dumps({"thread_id": "t3", "channel_id": "c2", "timestamp": "2024-01-04T00:00:00Z"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    backend = JsonlMessageStoreBackend(store)

    # Filter to c1; expected order: t1 (2024-01-03), t2 (2024-01-02)
    req = MessageThreadListRequest(channel_id="c1", limit=1)
    out = list_message_threads(req, backend=backend)

    assert [t.thread_id for t in out.threads] == ["t1"]
    assert out.next_cursor == "1"

    req2 = MessageThreadListRequest(channel_id="c1", limit=10, cursor=out.next_cursor)
    out2 = list_message_threads(req2, backend=backend)

    assert [t.thread_id for t in out2.threads] == ["t2"]
    assert out2.next_cursor is None


def test_jsonl_backend_invalid_cursor_is_invalid_input(tmp_path):
    store = tmp_path / "messages.jsonl"
    store.write_text(json.dumps({"thread_id": "t1"}) + "\n", encoding="utf-8")

    backend = JsonlMessageStoreBackend(store)
    req = MessageThreadListRequest(limit=1, cursor="not-an-int")

    with pytest.raises(MessageThreadListInvalidInput):
        list_message_threads(req, backend=backend)


def test_jsonl_backend_bad_json_is_external_failure(tmp_path):
    store = tmp_path / "messages.jsonl"
    store.write_text("{not json}\n", encoding="utf-8")

    backend = JsonlMessageStoreBackend(store)
    req = MessageThreadListRequest(limit=1)

    with pytest.raises(MessageThreadListExternalError):
        list_message_threads(req, backend=backend)


def test_cli_json_success(monkeypatch):
    runner = CliRunner()

    def _fake_list(req, config=None):
        return MessageThreadListResponse(
            threads=[MessageThreadSummary(thread_id="t1", channel_id="c1", message_count=1)],
            next_cursor=None,
        )

    monkeypatch.setattr(
        "thomas.cli.commands.messages.p058_message_thread_list.list_message_threads",
        _fake_list,
    )

    result = runner.invoke(COMMAND, ["--json", "--limit", "1"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["threads"][0]["thread_id"] == "t1"


def test_cli_json_failure(monkeypatch):
    runner = CliRunner()

    def _fake_list(req, config=None):
        raise MessageThreadListInvalidInput("bad", details={"field": "limit"})

    monkeypatch.setattr(
        "thomas.cli.commands.messages.p058_message_thread_list.list_message_threads",
        _fake_list,
    )

    result = runner.invoke(COMMAND, ["--json", "--limit", "0"])
    assert result.exit_code != 0

    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
