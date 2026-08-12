import asyncio

import httpx
import pytest

from thomas.core.config import ModelConfig
from thomas.core.llm import LLMClient, StreamEvent
from thomas.core.llm_shared import LLMError


class _FakeStreamResponse:
    def __init__(self, lines, status_code=200):
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b""


class _FakeClient:
    def __init__(self, lines, status_code=200):
        self._lines = lines
        self._status_code = status_code
        self.last_request = None

    def stream(self, method, url, json=None, params=None, headers=None):  # noqa: ANN001
        self.last_request = {"method": method, "url": url, "json": json, "params": params, "headers": headers or {}}
        return _FakeStreamResponse(self._lines, status_code=self._status_code)


class _TransportFailureResponse(_FakeStreamResponse):
    async def aiter_lines(self):
        for line in self._lines:
            yield line
        raise httpx.RemoteProtocolError("peer closed incomplete response")


class _EnterTransportFailureResponse(_FakeStreamResponse):
    async def __aenter__(self):
        raise httpx.RemoteProtocolError("peer closed before response headers")


class _SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.request_count = 0
        self.last_request = None

    def stream(self, method, url, json=None, params=None, headers=None):  # noqa: ANN001
        self.request_count += 1
        self.last_request = {"method": method, "url": url, "json": json, "params": params, "headers": headers or {}}
        return self.responses.pop(0)


class _TestableLLMClient(LLMClient):
    def __init__(self, config: ModelConfig, fake_client: _FakeClient):
        super().__init__(config)
        self._fake_client = fake_client

    async def _get_client(self):  # type: ignore[override]
        return self._fake_client


def _make_client(lines):
    cfg = ModelConfig(
        name="openai",
        provider="openai_compat",
        base_url="http://localhost:11434/v1",
        model="qwen2.5-coder:7b",
    )
    return _TestableLLMClient(cfg, _FakeClient(lines))


def _collect_events(llm: LLMClient, tools=None):
    async def run_once():
        events = []
        async for ev in llm.stream_chat([{"role": "user", "content": "hello"}], tools=tools):
            events.append(ev)
        return events

    return asyncio.run(run_once())


def test_openai_stream_parses_legacy_function_call_deltas() -> None:
    lines = [
        'data: {"choices":[{"delta":{"function_call":{"name":"fs.read_file"}}}]}',
        'data: {"choices":[{"delta":{"function_call":{"arguments":"{\\"path\\":\\"README.md\\"}"}}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"function_call"}]}',
        "data: [DONE]",
    ]
    llm = _make_client(lines)
    events = _collect_events(llm)

    starts = [e for e in events if e.type == "tool_call_start"]
    ends = [e for e in events if e.type == "tool_call_end"]
    done = [e for e in events if e.type == "done"]

    assert len(starts) == 1
    assert len(ends) == 1
    assert len(done) == 1
    assert ends[0].data["name"] == "fs.read_file"
    assert ends[0].data["arguments"] == '{"path":"README.md"}'


def test_openai_stream_accepts_dict_tool_arguments() -> None:
    lines = [
        (
            'data: {"choices":[{"delta":{"tool_calls":[{"id":"call_1",'
            '"function":{"name":"fs.read_file","arguments":{"path":"README.md"}}}]}}]}'
        ),
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    llm = _make_client(lines)
    events = _collect_events(llm)

    ends = [e for e in events if e.type == "tool_call_end"]
    assert len(ends) == 1
    assert ends[0].data["name"] == "fs.read_file"
    assert "README.md" in ends[0].data["arguments"]


def test_openai_compatible_stream_rejects_eof_without_done() -> None:
    with pytest.raises(LLMError, match=r"before the \[DONE\] confirmation"):
        _collect_events(_make_client([]))


def test_stream_chat_accepts_coroutine_stream_openai(monkeypatch) -> None:
    cfg = ModelConfig(
        name="openai_compat",
        provider="openai_compat",
        base_url="https://localhost",
        model="qwen",
    )
    llm = LLMClient(cfg)

    async def _fake_stream_openai(_llm, _messages, _tools=None):
        async def _stream():
            yield StreamEvent(type="token", data={"text": "ok"})
            yield StreamEvent(type="done", data={})

        return _stream()

    async def run() -> list:
        events = []
        async for event in llm.stream_chat([{"role": "user", "content": "hello"}], tools=None):
            events.append(event)
        return events

    monkeypatch.setattr("thomas.core.llm_client.stream_openai", _fake_stream_openai)
    events = asyncio.run(run())

    assert [e.type for e in events] == ["token", "done"]


def test_openai_codex_responses_stream_parses_text_usage_and_tools() -> None:
    lines = [
        "event: response.output_item.added",
        'data: {"type":"response.output_item.added","item":{"type":"function_call","call_id":"call_1","name":"fs_read_file"}}',
        "",
        "event: response.function_call_arguments.delta",
        'data: {"type":"response.function_call_arguments.delta","call_id":"call_1","delta":"{\\"path\\":"}',
        "",
        "event: response.function_call_arguments.delta",
        'data: {"type":"response.function_call_arguments.delta","call_id":"call_1","delta":"\\"README.md\\"}"}',
        "",
        "event: response.output_item.done",
        'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"call_1","name":"fs_read_file","arguments":"{\\"path\\":\\"README.md\\"}"}}',
        "",
        "event: response.output_text.delta",
        'data: {"type":"response.output_text.delta","delta":"done"}',
        "",
        "event: response.completed",
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":3,"output_tokens":4,"total_tokens":7}}}',
        "",
    ]
    cfg = ModelConfig(
        name="chatgpt",
        provider="openai_codex",
        base_url="https://chatgpt.com/backend-api/codex",
        model="gpt-5.6-sol",
        api_key="access-token",
        reasoning_effort="xhigh",
    )
    fake_client = _FakeClient(lines)
    llm = _TestableLLMClient(cfg, fake_client)
    events = _collect_events(
        llm,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "fs.read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )

    assert fake_client.last_request["url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert fake_client.last_request["headers"]["Authorization"] == "Bearer access-token"
    assert fake_client.last_request["json"]["model"] == "gpt-5.6-sol"
    assert fake_client.last_request["json"]["reasoning"] == {"effort": "xhigh"}
    assert fake_client.last_request["json"]["tools"][0]["name"] == "fs_read_file"
    assert [e.type for e in events].count("done") == 1
    token_events = [e for e in events if e.type == "token"]
    assert token_events[0].data["text"] == "done"
    ends = [e for e in events if e.type == "tool_call_end"]
    assert ends[0].data["name"] == "fs.read_file"
    assert ends[0].data["arguments"] == '{"path":"README.md"}'
    assert llm.session_usage.total_tokens == 7


def _codex_client(fake_client, *, retries: int) -> LLMClient:
    cfg = ModelConfig(
        name="chatgpt",
        provider="openai_codex",
        base_url="https://chatgpt.com/backend-api/codex",
        model="gpt-5.6-sol",
        api_key="access-token",
    )
    llm = _TestableLLMClient(cfg, fake_client)
    llm._max_retries = retries
    llm._base_retry_delay = 0
    return llm


def test_openai_codex_retries_transport_disconnect_before_any_event() -> None:
    fake_client = _SequenceClient(
        [
            _TransportFailureResponse([]),
            _FakeStreamResponse(
                [
                    "event: response.completed",
                    'data: {"type":"response.completed","response":{"usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2}}}',
                    "",
                ]
            ),
        ]
    )

    events = _collect_events(_codex_client(fake_client, retries=2))

    assert fake_client.request_count == 2
    assert [event.type for event in events].count("done") == 1


def test_openai_codex_transport_failure_entering_stream_keeps_real_error() -> None:
    fake_client = _SequenceClient([_EnterTransportFailureResponse([])])

    async def run_once() -> None:
        with pytest.raises(LLMError, match="before any usable output") as raised:
            async for _event in _codex_client(fake_client, retries=1).stream_chat(
                [{"role": "user", "content": "continue"}]
            ):
                pass
        assert "UnboundLocalError" not in str(raised.value)

    asyncio.run(run_once())


def test_openai_codex_does_not_retry_or_leak_traceback_after_partial_output() -> None:
    fake_client = _SequenceClient(
        [
            _TransportFailureResponse(
                [
                    "event: response.output_text.delta",
                    'data: {"type":"response.output_text.delta","delta":"partial"}',
                    "",
                ]
            )
        ]
    )
    events = []

    async def run_once() -> None:
        with pytest.raises(LLMError, match="disconnected after partial output") as raised:
            async for event in _codex_client(fake_client, retries=2).stream_chat(
                [{"role": "user", "content": "continue"}]
            ):
                events.append(event)
        assert "Traceback" not in str(raised.value)

    asyncio.run(run_once())

    assert fake_client.request_count == 1
    assert [event.data.get("text") for event in events if event.type == "token"] == ["partial"]


def test_openai_codex_requires_confirmed_terminal_event() -> None:
    fake_client = _SequenceClient([_FakeStreamResponse([])])

    async def run_once() -> None:
        with pytest.raises(LLMError, match="before confirming the response completed"):
            async for _event in _codex_client(fake_client, retries=1).stream_chat(
                [{"role": "user", "content": "continue"}]
            ):
                pass

    asyncio.run(run_once())
    assert fake_client.request_count == 1


def test_openai_codex_rejects_incomplete_terminal_response() -> None:
    fake_client = _SequenceClient(
        [
            _FakeStreamResponse(
                [
                    "event: response.incomplete",
                    'data: {"type":"response.incomplete","response":{"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"}}}',
                    "",
                ]
            )
        ]
    )

    async def run_once() -> None:
        with pytest.raises(LLMError, match=r"incomplete \(max_output_tokens\)"):
            async for _event in _codex_client(fake_client, retries=1).stream_chat(
                [{"role": "user", "content": "continue"}]
            ):
                pass

    asyncio.run(run_once())


def test_openai_codex_keeps_confirmed_completion_after_transport_close() -> None:
    fake_client = _SequenceClient(
        [
            _TransportFailureResponse(
                [
                    "event: response.completed",
                    'data: {"type":"response.completed","response":{"usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2}}}',
                    "",
                ]
            )
        ]
    )

    events = _collect_events(_codex_client(fake_client, retries=2))

    assert fake_client.request_count == 1
    assert [event.type for event in events] == ["usage", "done"]
