import asyncio

from thomas.core.config import ModelConfig
from thomas.core.llm import LLMClient


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

    def stream(self, method, url, json=None, params=None):  # noqa: ANN001
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


def _collect_events(llm: LLMClient, *, tools=None):
    async def run_once():
        events = []
        async for ev in llm.stream_chat([{"role": "user", "content": "hello"}], tools=tools):
            events.append(ev)
        return events

    return asyncio.run(run_once())


def test_p151_stream_accepts_data_prefix_without_space() -> None:
    lines = [
        'data:{"choices":[{"delta":{"content":"hello"}}]}',
        "data:[DONE]",
    ]
    llm = _make_client(lines)
    events = _collect_events(llm)

    tokens = [e.data["text"] for e in events if e.type == "token"]
    done = [e for e in events if e.type == "done"]

    assert tokens == ["hello"]
    assert len(done) == 1


def test_p151_stream_accepts_tool_calls_object_shape() -> None:
    lines = [
        (
            'data: {"choices":[{"delta":{"tool_calls":{"id":"call_1",'
            '"function":{"name":"fs.read_file","arguments":"{\\"path\\":\\"README.md\\"}"}}}}]}'
        ),
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    llm = _make_client(lines)
    events = _collect_events(llm)

    ends = [e for e in events if e.type == "tool_call_end"]
    assert len(ends) == 1
    assert ends[0].data["id"] == "call_1"
    assert ends[0].data["name"] == "fs.read_file"
    assert ends[0].data["arguments"] == '{"path":"README.md"}'


def test_p151_stream_preserves_multiple_tool_calls_without_indices() -> None:
    lines = [
        (
            'data: {"choices":[{"delta":{"tool_calls":['
            '{"id":"call_a","function":{"name":"tool.alpha","arguments":"{\\"a\\":1}"}},'
            '{"id":"call_b","function":{"name":"tool.beta","arguments":"{\\"b\\":2}"}}'
            "]}}]}"
        ),
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    llm = _make_client(lines)
    events = _collect_events(llm)

    ends = [e for e in events if e.type == "tool_call_end"]
    assert len(ends) == 2
    by_id = {e.data["id"]: e.data for e in ends}

    assert by_id["call_a"]["name"] == "tool.alpha"
    assert by_id["call_a"]["arguments"] == '{"a":1}'
    assert by_id["call_b"]["name"] == "tool.beta"
    assert by_id["call_b"]["arguments"] == '{"b":2}'


def test_p151_stream_continues_single_tool_call_when_provider_omits_id_and_index() -> None:
    lines = [
        ('data: {"choices":[{"delta":{"tool_calls":[{"id":"call_1","index":0,"function":{"name":"fs.read_file"}}]}}]}'),
        ('data: {"choices":[{"delta":{"tool_calls":[{"function":{"arguments":"{\\"path\\":\\"README.md\\"}"}}]}}]}'),
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    llm = _make_client(lines)
    events = _collect_events(llm)

    starts = [e for e in events if e.type == "tool_call_start"]
    deltas = [e for e in events if e.type == "tool_call_delta"]
    ends = [e for e in events if e.type == "tool_call_end"]

    assert len(starts) == 1
    assert len(deltas) == 1
    assert len(ends) == 1
    assert starts[0].data["id"] == "call_1"
    assert deltas[0].data["id"] == "call_1"
    assert ends[0].data["id"] == "call_1"
    assert ends[0].data["name"] == "fs.read_file"
    assert ends[0].data["arguments"] == '{"path":"README.md"}'


def test_p151_legacy_function_call_name_reverse_maps_sanitized_tool_name() -> None:
    lines = [
        'data: {"choices":[{"delta":{"function_call":{"name":"fs_read_file"}}}]}',
        'data: {"choices":[{"delta":{"function_call":{"arguments":"{\\"path\\":\\"README.md\\"}"}}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"function_call"}]}',
        "data: [DONE]",
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "fs.read_file",
                "description": "Read file",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    llm = _make_client(lines)
    events = _collect_events(llm, tools=tools)

    ends = [e for e in events if e.type == "tool_call_end"]
    assert len(ends) == 1
    assert ends[0].data["name"] == "fs.read_file"
    assert ends[0].data["arguments"] == '{"path":"README.md"}'
