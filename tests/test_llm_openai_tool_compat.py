import asyncio

from thomas.core.config import ModelConfig
from thomas.core.llm import LLMClient, StreamEvent


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
        model="gpt-5.5",
        api_key="access-token",
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
    assert fake_client.last_request["json"]["model"] == "gpt-5.5"
    assert fake_client.last_request["json"]["tools"][0]["name"] == "fs_read_file"
    assert [e.type for e in events].count("done") == 1
    token_events = [e for e in events if e.type == "token"]
    assert token_events[0].data["text"] == "done"
    ends = [e for e in events if e.type == "tool_call_end"]
    assert ends[0].data["name"] == "fs.read_file"
    assert ends[0].data["arguments"] == '{"path":"README.md"}'
    assert llm.session_usage.total_tokens == 7
