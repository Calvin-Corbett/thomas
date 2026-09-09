import json

from thomas.core.config import ModelConfig
from thomas.core.llm import LLMClient


def _make_client() -> LLMClient:
    cfg = ModelConfig(
        name="anthropic",
        provider="anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-3-5-sonnet",
    )
    return LLMClient(cfg)


def _flatten_tool_results(messages):
    out = []
    for msg in messages:
        if str(msg.get("role") or "") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and str(block.get("type") or "") == "tool_result":
                out.append(block)
    return out


def test_anthropic_request_keeps_valid_tool_result_pairing() -> None:
    llm = _make_client()
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "toolu_abc123",
                    "type": "function",
                    "function": {"name": "fs.read_file", "arguments": json.dumps({"path": "README.md"})},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "toolu_abc123", "content": "ok"},
    ]

    body = llm._build_anthropic_request(messages, tools=None, stream=True)
    anthropic_messages = body.get("messages") or []
    tool_results = _flatten_tool_results(anthropic_messages)

    assert len(tool_results) == 1
    assert tool_results[0].get("tool_use_id") == "toolu_abc123"


def test_anthropic_request_drops_orphan_tool_result_without_matching_tool_use() -> None:
    llm = _make_client()
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "tool", "tool_call_id": "toolu_orphan", "content": "result"},
    ]

    body = llm._build_anthropic_request(messages, tools=None, stream=True)
    anthropic_messages = body.get("messages") or []
    tool_results = _flatten_tool_results(anthropic_messages)

    assert tool_results == []


def test_anthropic_request_drops_mismatched_tool_result_id() -> None:
    llm = _make_client()
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "toolu_expected",
                    "type": "function",
                    "function": {"name": "fs.read_file", "arguments": json.dumps({"path": "README.md"})},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "toolu_other", "content": "result"},
    ]

    body = llm._build_anthropic_request(messages, tools=None, stream=True)
    anthropic_messages = body.get("messages") or []
    tool_results = _flatten_tool_results(anthropic_messages)

    assert tool_results == []
