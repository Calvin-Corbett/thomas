"""A tool call the model writes as text is heard as a tool call (2026-09-07).

Driving the chat on :8977 with a local model (qwen2.5-coder:7b through the
OpenAI-compatible path), two replies in a row were the whole tool call written
into the content::

    ```json
    {"name": "recall", "arguments": {"query": "clear day sky color"}}
    ```

The model had decided to call a tool; nothing ran, and the JSON was shown as
the answer. Models without native tool calling do this, and every serious
OpenAI-compatible client parses it. Thomas's stream client now holds content
that opens like JSON while a request carried tools, and when the finished
content is one call to a tool that was offered, emits the tool-call events
the loop already understands, with everything downstream (fence, policy,
execution) unchanged. Content that turns out not to be a call is released as
text, nothing lost; a request without tools is never touched, so a reply that
was asked for in JSON stays a reply.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from thomas.core.config import ModelConfig
from thomas.core.llm_client import LLMClient
from thomas.core.llm_shared import embedded_tool_call
from thomas.core.llm_streaming import stream_openai

TOOLS = [
    {"type": "function", "function": {"name": "recall", "parameters": {"type": "object"}}},
    {"type": "function", "function": {"name": "fs.read_file", "parameters": {"type": "object"}}},
]
MESSAGES = [{"role": "user", "content": "what colour is the sky?"}]


def _sse(pieces: list[str]) -> bytes:
    lines = []
    for piece in pieces:
        chunk = {"choices": [{"delta": {"content": piece}, "index": 0}]}
        lines.append("data: " + json.dumps(chunk))
    lines.append('data: {"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]}')
    lines.append("data: [DONE]")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _events(pieces: list[str], *, tools):
    client = LLMClient(ModelConfig(name="t", provider="ollama", base_url="http://127.0.0.1:1/v1", model="qwen"))
    body = _sse(pieces)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    async def fake_client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    client._get_client = fake_client  # type: ignore[method-assign]

    async def go():
        out = []
        async for event in stream_openai(client, list(MESSAGES), tools):
            out.append((event.type, dict(event.data or {})))
        return out

    return asyncio.run(go())


def _types(events):
    return [t for t, _ in events]


def test_the_parser_reads_the_shapes_models_write() -> None:
    names = {"recall", "fs.read_file", "fs_read_file"}
    fenced = '```json\n{"name": "recall", "arguments": {"query": "sky"}}\n```'
    assert embedded_tool_call(fenced, names) == ("recall", '{"query": "sky"}')
    assert embedded_tool_call('{"name": "recall", "arguments": "{\\"query\\": \\"sky\\"}"}', names) == (
        "recall",
        '{"query": "sky"}',
    )
    assert embedded_tool_call('{"function": {"name": "fs_read_file", "arguments": {"path": "a"}}}', names) == (
        "fs_read_file",
        '{"path": "a"}',
    )
    assert embedded_tool_call('{"name": "make_coffee", "arguments": {}}', names) is None
    assert embedded_tool_call('{"answer": 42}', names) is None
    assert embedded_tool_call("The sky is blue.", names) is None
    assert embedded_tool_call('{"name": "recall", "arguments": {"q": 1}} and then some prose', names) is None


def test_a_content_tool_call_becomes_tool_call_events_and_no_text() -> None:
    events = _events(['```json\n{"name": "rec', 'all", "arguments": {"query": "clear day sky"}}', "\n```"], tools=TOOLS)
    kinds = _types(events)
    assert "token" not in kinds, kinds
    assert kinds.index("tool_call_start") < kinds.index("tool_call_end") < kinds.index("done")
    end = dict(events[kinds.index("tool_call_end")][1])
    assert end["name"] == "recall"
    assert json.loads(end["arguments"]) == {"query": "clear day sky"}


def test_json_that_is_not_a_call_is_released_as_text_with_nothing_lost() -> None:
    events = _events(['{"answer": ', "42}"], tools=TOOLS)
    kinds = _types(events)
    assert "tool_call_start" not in kinds
    assert "".join(d["text"] for t, d in events if t == "token") == '{"answer": 42}'


def test_prose_streams_live_and_a_request_without_tools_is_never_held() -> None:
    prose = _events(["The sky ", "is blue."], tools=TOOLS)
    assert _types(prose)[:2] == ["token", "token"]
    asked_for_json = _events(['{"name": "recall", "arguments": {"query": "x"}}'], tools=None)
    assert _types(asked_for_json) == ["token", "done"]


def test_a_call_to_a_tool_that_was_not_offered_stays_text() -> None:
    events = _events(['{"name": "make_coffee", "arguments": {}}'], tools=TOOLS)
    assert "tool_call_start" not in _types(events)
    assert "".join(d["text"] for t, d in events if t == "token") == '{"name": "make_coffee", "arguments": {}}'
