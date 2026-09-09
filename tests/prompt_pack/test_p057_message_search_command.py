import json
from pathlib import Path

import pytest

from thomas.messages.p057_message_search_command import (
    MessageSearchBackend,
    MessageSearchExternalFailure,
    MessageSearchInput,
    MessageSearchInvalidInput,
    MessageSearchMissingConfig,
    search_messages,
    validate_message_search_input,
)


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: object | None = None, text: str | None = None):
        self.status_code = int(status_code)
        self._payload = payload
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeHttpClient:
    def __init__(self, handler):
        self._handler = handler

    def get(self, url: str, *, params=None, headers=None):
        return self._handler(url, params or [], headers or {})


def test_validate_rejects_blank_query() -> None:
    with pytest.raises(MessageSearchInvalidInput) as exc:
        validate_message_search_input(query="   ")
    assert exc.value.code == "invalid_input"
    assert "query" in str(exc.value).lower()


def test_missing_config_is_deterministic_when_no_backend_available() -> None:
    req = MessageSearchInput(query="hello", limit=5)
    with pytest.raises(MessageSearchMissingConfig) as exc:
        search_messages(req, runtime_or_config={}, backend=MessageSearchBackend.AUTO)
    assert exc.value.code == "missing_config"
    assert "backend" in str(exc.value).lower() or "configured" in str(exc.value).lower()


def test_local_store_success(tmp_path: Path) -> None:
    store = tmp_path / "messages.jsonl"
    store.write_text(
        "\n".join(
            [
                json.dumps(
                    {"id": "1", "channel_id": "c1", "author_id": "u1", "content": "hello world", "timestamp": "t"}
                ),
                json.dumps({"id": "2", "channel_id": "c2", "author_id": "u2", "content": "nothing here"}),
                json.dumps({"id": "3", "channel_id": "c1", "author_id": "u2", "content": "world domination"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = {"messages": {"store_path": str(store)}}
    req = MessageSearchInput(query="world", limit=10, channel_ids=("c1",))

    out = search_messages(req, runtime_or_config=cfg, backend=MessageSearchBackend.AUTO)
    assert out.total_results == 2
    assert len(out.hits) == 2
    assert {h.message_id for h in out.hits} == {"1", "3"}


def test_local_store_missing_file_is_external_failure(tmp_path: Path) -> None:
    cfg = {"messages": {"store_path": str(tmp_path / "missing.jsonl")}}
    req = MessageSearchInput(query="x", limit=5)

    with pytest.raises(MessageSearchExternalFailure) as exc:
        search_messages(req, runtime_or_config=cfg, backend=MessageSearchBackend.LOCAL)

    assert exc.value.code == "external_failure"
    assert "store" in str(exc.value).lower()


def test_discord_success_parses_search_payload() -> None:
    def handler(url, params, headers):
        assert url.endswith("/guilds/123/messages/search")
        assert ("content", "needle") in params
        assert ("limit", "2") in params
        assert headers.get("Authorization")
        return _FakeResponse(
            status_code=200,
            payload={
                "total_results": 1,
                "messages": [
                    [
                        {
                            "id": "111",
                            "channel_id": "222",
                            "content": "needle in a haystack",
                            "timestamp": "2026-02-20T00:00:00.000Z",
                            "author": {"id": "333"},
                        }
                    ]
                ],
            },
        )

    client = _FakeHttpClient(handler)
    cfg = {"channels": {"discord": {"token": "Bearer test", "api_base": "https://discord.test/api/v9"}}}

    req = MessageSearchInput(query="needle", guild_id="123", limit=2)
    out = search_messages(req, runtime_or_config=cfg, backend=MessageSearchBackend.DISCORD, http_client=client)

    assert out.total_results == 1
    assert len(out.hits) == 1
    hit = out.hits[0]
    assert hit.message_id == "111"
    assert hit.channel_id == "222"
    assert hit.author_id == "333"
    assert hit.url and hit.url.endswith("/123/222/111")


def test_discord_non_2xx_is_external_failure() -> None:
    def handler(url, params, headers):
        return _FakeResponse(status_code=500, text="nope")

    client = _FakeHttpClient(handler)
    cfg = {"channels": {"discord": {"token": "Bearer test", "api_base": "https://discord.test/api/v9"}}}

    req = MessageSearchInput(query="needle", guild_id="123", limit=2)

    with pytest.raises(MessageSearchExternalFailure) as exc:
        search_messages(req, runtime_or_config=cfg, backend=MessageSearchBackend.DISCORD, http_client=client)

    assert exc.value.code == "external_failure"
    assert exc.value.details.get("status_code") == 500
