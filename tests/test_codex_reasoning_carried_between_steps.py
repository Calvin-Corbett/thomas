"""GPT keeps its reasoning across the tool steps of one turn (ChatGPT/Codex Responses path).

The request is sent with ``store: false``, so the provider keeps nothing between
calls: unless the request asks for ``reasoning.encrypted_content`` and the next
request carries those reasoning items back in front of the calls they produced,
the model re-derives its plan on every tool step. These tests drive the real
stream parser and request builder with a fake transport.
"""

from __future__ import annotations

import asyncio
import json

from thomas.core.config import ModelConfig
from thomas.core.llm import LLMClient
from thomas.core.llm_streaming_codex import _REASONING_KEEP, _remember_reasoning, _responses_input_from_messages


class _Resp:
    def __init__(self, lines):
        self._lines = lines
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b""


class _Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def stream(self, method, url, json=None, params=None, headers=None):  # noqa: ANN001
        self.requests.append(json)
        return _Resp(self.responses.pop(0))


class _Client(LLMClient):
    def __init__(self, transport):
        super().__init__(
            ModelConfig(
                name="chatgpt",
                provider="openai_codex",
                base_url="https://chatgpt.com/backend-api/codex",
                model="gpt-5.6-sol",
                api_key="access-token",
                reasoning_effort="high",
            )
        )
        self._transport = transport
        self._max_retries = 0
        self._base_retry_delay = 0

    async def _get_client(self):  # type: ignore[override]
        return self._transport


def _sse(*payloads: dict) -> list[str]:
    lines: list[str] = []
    for payload in payloads:
        lines += [f"event: {payload['type']}", "data: " + json.dumps(payload), ""]
    return lines


def _call_item(call_id: str) -> dict:
    return {
        "type": "function_call",
        "id": "fc_" + call_id,
        "call_id": call_id,
        "name": "fs_read_file",
        "arguments": "{}",
    }


def _assistant_call(call_id: str) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "fs.read_file", "arguments": "{}"}}],
    }


REASONING = {
    "type": "reasoning",
    "id": "rs_1",
    "summary": [{"type": "summary_text", "text": "Read the README first."}],
    "encrypted_content": "gAAAAB-opaque",
}
COMPLETED = {"type": "response.completed", "response": {"usage": {"input_tokens": 1, "output_tokens": 1}}}
STEP_ONE = _sse(
    {"type": "response.output_item.done", "item": REASONING},
    {"type": "response.output_item.added", "item": _call_item("call_1")},
    {"type": "response.output_item.done", "item": _call_item("call_1")},
    COMPLETED,
)
STEP_TWO = _sse({"type": "response.output_text.delta", "delta": "done"}, COMPLETED)
TOOLS = [
    {"type": "function", "function": {"name": "fs.read_file", "description": "", "parameters": {"type": "object"}}}
]


async def _drain(llm, messages):
    return [ev async for ev in llm.stream_chat(messages, tools=TOOLS)]


def test_reasoning_from_one_step_is_sent_back_in_front_of_its_call() -> None:
    transport = _Transport(STEP_ONE, STEP_TWO)
    llm = _Client(transport)
    history = [{"role": "system", "content": "sys"}, {"role": "user", "content": "build it"}]
    asyncio.run(_drain(llm, history))
    history += [_assistant_call("call_1"), {"role": "tool", "tool_call_id": "call_1", "content": "readme text"}]
    asyncio.run(_drain(llm, history))

    first, second = transport.requests
    assert first["store"] is False
    assert first["include"] == ["reasoning.encrypted_content"]
    kinds = [item.get("type") or item.get("role") for item in second["input"]]
    assert kinds == ["user", "reasoning", "function_call", "function_call_output"]
    assert second["input"][1] == REASONING


def test_reasoning_from_an_earlier_turn_is_not_resent() -> None:
    llm = _Client(_Transport())
    _remember_reasoning(llm, [dict(REASONING)], ["call_1"])
    messages = [
        {"role": "user", "content": "build it"},
        _assistant_call("call_1"),
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        {"role": "assistant", "content": "built"},
        {"role": "user", "content": "now add a score"},
    ]
    _instructions, items = _responses_input_from_messages(llm, messages)
    assert not any(item.get("type") == "reasoning" for item in items)


def test_reasoning_without_encrypted_content_is_never_replayed_and_the_store_is_bounded() -> None:
    bare = {"type": "reasoning", "id": "rs_x", "summary": []}
    step = _sse(
        {"type": "response.output_item.done", "item": bare},
        {"type": "response.output_item.done", "item": _call_item("call_9")},
        COMPLETED,
    )
    llm = _Client(_Transport(step))
    asyncio.run(_drain(llm, [{"role": "user", "content": "go"}]))
    assert "call_9" not in (getattr(llm, "_codex_reasoning_by_call", None) or {})
    for n in range(_REASONING_KEEP + 10):
        _remember_reasoning(llm, [dict(REASONING)], [f"call_{n}"])
    assert len(llm._codex_reasoning_by_call) == _REASONING_KEEP
