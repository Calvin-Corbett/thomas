"""An overloaded provider response gets the same second attempt as HTTP 503."""

import json
from unittest.mock import AsyncMock

import pytest

from tests.test_llm_budget_transport import _Client, _Response
from thomas.core.config import ModelConfig
from thomas.core.llm_client import LLMClient
from thomas.core.llm_shared import RETRYABLE_STATUS


def test_529_is_a_retryable_status() -> None:
    assert 529 in RETRYABLE_STATUS


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai_compat", "openai_codex", "anthropic"])
@pytest.mark.parametrize("first_status", [503, 529])
async def test_overloaded_transport_tries_again(monkeypatch, provider: str, first_status: int) -> None:
    llm = LLMClient(
        ModelConfig(
            name="fixture",
            provider=provider,
            base_url="https://fixture.invalid",
            api_key="fixture-token",
            model="test",
            max_tokens=7,
        ),
        max_retries=2,
        base_retry_delay_s=0,
    )
    if provider == "openai_compat":
        lines = ['data: {"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}', "data: [DONE]"]
    elif provider == "openai_codex":
        lines = [
            "data: "
            + json.dumps(
                {
                    "type": "response.completed",
                    "response": {"usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}},
                }
            ),
            "",
            "data: [DONE]",
            "",
        ]
    else:
        lines = [
            'data: {"type":"message_start","message":{"usage":{"input_tokens":1}}}',
            'data: {"type":"message_delta","usage":{"output_tokens":1},"delta":{"stop_reason":"end_turn"}}',
            'data: {"type":"message_stop"}',
        ]
    client = _Client([_Response([], status=first_status), _Response(lines)])
    monkeypatch.setattr(llm, "_get_client", AsyncMock(return_value=client))

    events = [event async for event in llm.stream_chat([{"role": "user", "content": "hello"}])]

    assert len(client.bodies) == 2
    assert any(event.type == "done" for event in events)
