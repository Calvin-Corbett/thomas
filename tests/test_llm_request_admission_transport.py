import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from tests.test_llm_budget_transport import _Client, _Response
from thomas.core.config import ModelConfig
from thomas.core.llm_client import LLMClient
from thomas.core.llm_request_admission import RequestAdmission
from thomas.server.chat_budget_ledger import ChatBudgetLedger
from thomas.server.chat_budget_scope import ChatBudgetScope


def setup(tmp_path, provider):
    admission = RequestAdmission(ceiling=2)
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
        request_admission=admission,
    )
    scope = ChatBudgetScope(
        ledger=ChatBudgetLedger(tmp_path / "budget.db"),
        user_id="test",
        session_id="chat",
        session_budget=100000,
        daily_budget=100000,
        throttle=True,
    )
    llm.set_budget_scope(scope)
    return llm, admission, scope


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai_compat", "openai_codex", "anthropic"])
async def test_actual_provider_retry_gets_a_new_admission_and_keeps_budget(tmp_path, monkeypatch, provider):
    llm, admission, scope = setup(tmp_path, provider)
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
    client = _Client([_Response([], status=503), _Response(lines)])
    monkeypatch.setattr(llm, "_get_client", AsyncMock(return_value=client))
    async for _ in llm.stream_chat([{"role": "user", "content": "hello"}]):
        pass
    assert len(client.bodies) == admission.snapshot()["admitted"] == admission.snapshot()["settled"] == 2
    assert admission.snapshot()["inflight"] == 0
    assert scope.charged_tokens > 0
    assert (await scope.ledger.snapshot(user_id="test", session_id="chat")).session_tokens == scope.charged_tokens


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai_compat", "openai_codex", "anthropic"])
async def test_cancel_before_send_releases_budget_and_does_not_invoke_http(tmp_path, monkeypatch, provider):
    llm, admission, scope = setup(tmp_path, provider)
    held = [await admission.acquire() for _ in range(2)]
    client = _Client([])
    monkeypatch.setattr(llm, "_get_client", AsyncMock(return_value=client))

    async def consume():
        async for _ in llm.stream_chat([{"role": "user", "content": "hello"}]):
            pass

    task = asyncio.create_task(consume())
    async with asyncio.timeout(5):
        while admission.snapshot()["waiting"] != 1:
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not client.bodies
    assert scope.charged_tokens == 0
    assert (await scope.ledger.snapshot(user_id="test", session_id="chat")).session_tokens == 0
    for ticket in held:
        admission.release(ticket)
    assert admission.snapshot()["waiting"] == admission.snapshot()["inflight"] == 0
