import asyncio
import unittest

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

    def stream(self, method, url, json=None):  # noqa: ANN001
        return _FakeStreamResponse(self._lines, status_code=self._status_code)


class _TestableLLMClient(LLMClient):
    def __init__(self, config: ModelConfig, fake_client: _FakeClient):
        super().__init__(config)
        self._fake_client = fake_client

    async def _get_client(self):  # type: ignore[override]
        return self._fake_client


class TestAnthropicUsageAccounting(unittest.TestCase):
    def _make_client(self, lines):
        cfg = ModelConfig(
            name="anthropic",
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-5-sonnet",
        )
        return _TestableLLMClient(cfg, _FakeClient(lines))

    def test_usage_event_includes_prompt_and_completion_tokens(self):
        lines = [
            'data: {"type":"message_start","message":{"usage":{"input_tokens":12}}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}',
            'data: {"type":"message_delta","usage":{"output_tokens":4}}',
            'data: {"type":"message_stop"}',
        ]
        llm = self._make_client(lines)

        async def run_once():
            events = []
            async for ev in llm.stream_chat([{"role": "user", "content": "hello"}], tools=None):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        usage_events = [e for e in events if e.type == "usage"]
        self.assertEqual(len(usage_events), 1)

        usage = usage_events[0].data["usage"]
        self.assertEqual(usage.prompt_tokens, 12)
        self.assertEqual(usage.completion_tokens, 4)
        self.assertEqual(usage.total_tokens, 16)
        self.assertEqual(llm.session_usage.prompt_tokens, 12)
        self.assertEqual(llm.session_usage.completion_tokens, 4)
        self.assertEqual(llm.session_usage.total_tokens, 16)

    def test_usage_counts_cache_input_tokens(self):
        lines = [
            (
                'data: {"type":"message_start","message":{"usage":'
                '{"input_tokens":10,"cache_creation_input_tokens":3,"cache_read_input_tokens":2}}}'
            ),
            'data: {"type":"message_delta","usage":{"output_tokens":5}}',
            'data: {"type":"message_stop"}',
        ]
        llm = self._make_client(lines)

        async def run_once():
            events = []
            async for ev in llm.stream_chat([{"role": "user", "content": "hello"}], tools=None):
                events.append(ev)
            return events

        events = asyncio.run(run_once())
        usage_events = [e for e in events if e.type == "usage"]
        self.assertEqual(len(usage_events), 1)
        usage = usage_events[0].data["usage"]
        self.assertEqual(usage.prompt_tokens, 15)
        self.assertEqual(usage.completion_tokens, 5)
        self.assertEqual(usage.total_tokens, 20)


if __name__ == "__main__":
    unittest.main()
