import asyncio

from thomas.core.config import ModelConfig
from thomas.core.llm import LLMClient, LLMError, StreamEvent


class _FailoverTestClient(LLMClient):
    def __init__(self, config, **kwargs):  # noqa: ANN001
        super().__init__(config, **kwargs)
        self.calls = []

    async def _stream_current_provider(self, messages, tools=None):  # noqa: ANN001
        self.calls.append(self.config.name)
        if self.config.name == "primary":
            raise LLMError("upstream unavailable", status=503, retryable=True)
        yield StreamEvent(type="token", data={"text": "ok"})
        yield StreamEvent(type="done", data={})


class _FlakyPrimaryClient(LLMClient):
    def __init__(self, config, **kwargs):  # noqa: ANN001
        super().__init__(config, **kwargs)
        self.calls = []
        self._primary_failures = 1

    async def _stream_current_provider(self, messages, tools=None):  # noqa: ANN001
        self.calls.append(self.config.name)
        if self.config.name == "primary" and self._primary_failures > 0:
            self._primary_failures -= 1
            raise LLMError("temporary primary failure", status=503, retryable=True)
        yield StreamEvent(type="token", data={"text": "ok"})
        yield StreamEvent(type="done", data={})


def test_llm_failover_switches_to_fallback_profile() -> None:
    primary = ModelConfig(name="primary", model="m1")
    fallback = ModelConfig(name="fallback", model="m2")
    client = _FailoverTestClient(
        primary,
        fallback_configs=[fallback],
        failover_enabled=True,
        failover_cooldown_s=10,
    )

    async def run_once():
        events = []
        async for ev in client.stream_chat([{"role": "user", "content": "hi"}], tools=None):
            events.append(ev.type)
        return events

    events = asyncio.run(run_once())
    assert events == ["token", "done"]
    assert client.calls == ["primary", "fallback"]


def test_llm_failover_retries_primary_on_next_turn() -> None:
    primary = ModelConfig(name="primary", model="m1")
    fallback = ModelConfig(name="fallback", model="m2")
    client = _FlakyPrimaryClient(
        primary,
        fallback_configs=[fallback],
        failover_enabled=True,
        failover_cooldown_s=0,
    )

    async def run_once():
        events = []
        async for ev in client.stream_chat([{"role": "user", "content": "hi"}], tools=None):
            events.append(ev.type)
        return events

    events1 = asyncio.run(run_once())
    events2 = asyncio.run(run_once())

    assert events1 == ["token", "done"]
    assert events2 == ["token", "done"]
    # First turn falls back; second turn starts from primary again.
    assert client.calls == ["primary", "fallback", "primary"]
