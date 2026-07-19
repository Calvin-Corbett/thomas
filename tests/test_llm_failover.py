import asyncio

from thomas.core.config import ModelConfig
from thomas.core.llm import LLMClient, LLMError, StreamEvent
from thomas.core.llm_shared import callable_accepts_keyword


def test_keyword_detection_rejects_positional_only_parameters() -> None:
    def _positional_only(turn_user_content, /):  # noqa: ANN001
        return turn_user_content

    assert callable_accepts_keyword(_positional_only, "turn_user_content") is False


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


class _PrimarySuccessClient(LLMClient):
    def __init__(self, config, **kwargs):  # noqa: ANN001
        super().__init__(config, **kwargs)
        self.calls = []

    async def _stream_current_provider(self, messages, tools=None):  # noqa: ANN001
        self.calls.append(self.config.name)
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
    trace = client.runtime_trace()
    assert trace.get("failover_used") is True
    assert trace.get("requested", {}).get("profile") == "primary"
    assert trace.get("active", {}).get("profile") == "fallback"
    attempts = trace.get("attempts") or []
    assert len(attempts) >= 2
    assert attempts[0].get("profile") == "primary"
    assert attempts[0].get("status") == "error"
    assert attempts[1].get("profile") == "fallback"
    assert attempts[1].get("status") == "success"


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
    aggregate = client.runtime_trace()
    assert aggregate["failover_used"] is True
    assert [attempt["profile"] for attempt in aggregate["attempts"]] == ["primary", "fallback", "primary"]

    client.reset_runtime_trace()
    empty_trace = client.runtime_trace()
    assert empty_trace["attempts"] == []
    assert empty_trace["active"] == {}
    assert empty_trace["failover_used"] is False
    asyncio.run(run_once())
    reset_trace = client.runtime_trace()
    assert reset_trace["failover_used"] is False
    assert [attempt["profile"] for attempt in reset_trace["attempts"]] == ["primary"]


def test_llm_runtime_trace_without_failover_reports_single_success() -> None:
    primary = ModelConfig(name="primary", model="m1")
    fallback = ModelConfig(name="fallback", model="m2")
    client = _PrimarySuccessClient(
        primary,
        fallback_configs=[fallback],
        failover_enabled=False,
    )

    async def run_once():
        events = []
        async for ev in client.stream_chat([{"role": "user", "content": "hi"}], tools=None):
            events.append(ev.type)
        return events

    events = asyncio.run(run_once())
    assert events == ["token", "done"]
    assert client.calls == ["primary"]
    trace = client.runtime_trace()
    assert trace.get("failover_enabled") is False
    assert trace.get("failover_used") is False
    attempts = trace.get("attempts") or []
    assert len(attempts) == 1
    assert attempts[0].get("profile") == "primary"
    assert attempts[0].get("status") == "success"
    client.reset_runtime_trace()
    assert client.runtime_trace()["attempts"] == []
    assert client.runtime_trace()["active"] == {}
