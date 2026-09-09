from __future__ import annotations

from thomas.server.routes.gateway.p149_compat_request_validation_layer import json_schema, validate_compat_request


def test_validate_openai_chat_completions_success() -> None:
    payload = {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.2,
        "stream": False,
        "max_tokens": 64,
    }
    res = validate_compat_request("openai_chat_completions", payload).to_dict()
    assert res["ok"] is True
    assert res["kind"] == "openai_chat_completions"
    assert res["normalized"]["model"] == "gpt-test"
    assert isinstance(res["normalized"]["messages"], list)
    assert res["errors"] == []


def test_validate_openai_chat_completions_failure_missing_model() -> None:
    payload = {"messages": [{"role": "user", "content": "hi"}]}
    res = validate_compat_request("openai_chat_completions", payload).to_dict()
    assert res["ok"] is False
    assert any(e["code"] == "missing_field" and e.get("path") == "$.model" for e in res["errors"])


def test_validate_openai_chat_completions_failure_bad_messages_type() -> None:
    payload = {"model": "gpt-test", "messages": "nope"}
    res = validate_compat_request("openai_chat_completions", payload).to_dict()
    assert res["ok"] is False
    assert any(e.get("path") == "$.messages" for e in res["errors"])


def test_validate_responses_create_requires_input_or_messages() -> None:
    payload = {"model": "gpt-test"}
    res = validate_compat_request("responses_create", payload).to_dict()
    assert res["ok"] is False
    assert any(e["code"] == "missing_field" for e in res["errors"])


def test_json_schema_is_stable() -> None:
    s = json_schema()
    assert s["type"] == "object"
    assert "kind" in s["required"]
    assert "payload" in s["required"]
    assert "openai_chat_completions" in s["properties"]["kind"]["enum"]
    assert "responses_create" in s["properties"]["kind"]["enum"]
