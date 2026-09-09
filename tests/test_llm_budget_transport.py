from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from thomas.core.config import ModelConfig
from thomas.core.llm_client import LLMClient
from thomas.core.llm_shared import LLMError
from thomas.server.chat_budget_ledger import ChatBudgetLedger
from thomas.server.chat_budget_scope import ChatBudgetScope, conservative_input_bound


class _Response:
    def __init__(self, lines: list[str], *, status: int = 200) -> None:
        self.status_code = status
        self.headers: dict[str, str] = {}
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):  # noqa: ANN002, ANN202
        return False

    async def aread(self) -> bytes:
        return b"fixture error"

    async def aiter_lines(self):  # noqa: ANN202
        for line in self._lines:
            yield line


class _Client:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.bodies: list[dict] = []

    def stream(self, _method, _url, *, json, **_kwargs):  # noqa: ANN001, ANN202
        self.bodies.append(dict(json))
        return self.responses.pop(0)


class _BlockingResponse(_Response):
    def __init__(self) -> None:
        super().__init__([])
        self.entered = asyncio.Event()

    async def aiter_lines(self):  # noqa: ANN202
        yield 'data: {"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}'
        self.entered.set()
        await asyncio.Event().wait()


async def _run_transport(
    tmp_path,
    *,
    provider: str,
    response_lines: list[str],
    api_key: str = "",
    model_max_tokens: int = 100,
    output_budget: int = 7,
) -> dict:
    messages = [{"role": "user", "content": "hello"}]
    input_bound = conservative_input_bound(messages, None)
    llm = LLMClient(
        ModelConfig(
            name="test",
            provider=provider,
            base_url="https://provider.invalid",
            api_key=api_key,
            model="fixture",
            max_tokens=model_max_tokens,
        ),
        max_retries=1,
    )
    scope = ChatBudgetScope(
        ledger=ChatBudgetLedger(tmp_path / f"{provider}.sqlite3"),
        user_id="u1",
        session_id="s1",
        session_budget=input_bound + output_budget,
        daily_budget=input_bound + output_budget,
        throttle=True,
    )
    llm.set_budget_scope(scope)
    client = _Client([_Response(response_lines)])
    with patch.object(llm, "_get_client", AsyncMock(return_value=client)):
        async for _event in llm.stream_chat(messages, None):
            pass
    await llm.close()
    return client.bodies[0]


@pytest.mark.asyncio
async def test_openai_transport_posts_the_reserved_output_cap(tmp_path) -> None:
    body = await _run_transport(
        tmp_path,
        provider="openai_compat",
        response_lines=[
            'data: {"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}',
            "data: [DONE]",
        ],
    )
    assert body["max_tokens"] == 7


@pytest.mark.asyncio
async def test_anthropic_transport_posts_the_reserved_output_cap(tmp_path) -> None:
    body = await _run_transport(
        tmp_path,
        provider="anthropic",
        response_lines=[
            'data: {"type":"message_start","message":{"usage":{"input_tokens":1}}}',
            'data: {"type":"message_delta","usage":{"output_tokens":1},"delta":{"stop_reason":"end_turn"}}',
            'data: {"type":"message_stop"}',
        ],
    )
    assert body["max_tokens"] == 7


@pytest.mark.asyncio
async def test_codex_responses_transport_omits_unsupported_output_cap(tmp_path) -> None:
    body = await _run_transport(
        tmp_path,
        provider="openai_codex",
        api_key="fixture-token",
        model_max_tokens=7,
        response_lines=[
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
        ],
    )
    assert "max_output_tokens" not in body


@pytest.mark.asyncio
async def test_codex_responses_transport_rejects_a_reduced_hard_cap(tmp_path) -> None:
    messages = [{"role": "user", "content": "hello"}]
    input_bound = conservative_input_bound(messages, None)
    llm = LLMClient(
        ModelConfig(
            name="test",
            provider="openai_codex",
            base_url="https://provider.invalid",
            api_key="fixture-token",
            model="fixture",
            max_tokens=100,
        ),
        max_retries=1,
    )
    scope = ChatBudgetScope(
        ledger=ChatBudgetLedger(tmp_path / "codex-reduced.sqlite3"),
        user_id="u1",
        session_id="s1",
        session_budget=input_bound + 7,
        daily_budget=input_bound + 7,
        throttle=True,
    )
    llm.set_budget_scope(scope)
    client = _Client([_Response([])])
    with patch.object(llm, "_get_client", AsyncMock(return_value=client)):
        with pytest.raises(LLMError, match="cannot safely enforce the reduced output budget"):
            async for _event in llm.stream_chat(messages, None):
                pass
    assert client.bodies == []
    assert (await scope.ledger.snapshot(user_id="u1", session_id="s1")).session_tokens == 0
    await llm.close()


@pytest.mark.asyncio
async def test_retry_re_admits_each_physical_request_without_multiplying_allowance(tmp_path) -> None:
    messages = [{"role": "user", "content": "hello"}]
    input_bound = conservative_input_bound(messages, None)
    llm = LLMClient(
        ModelConfig(
            name="test",
            provider="openai_compat",
            base_url="https://provider.invalid",
            model="fixture",
            max_tokens=7,
        ),
        max_retries=2,
        base_retry_delay_s=0,
    )
    scope = ChatBudgetScope(
        ledger=ChatBudgetLedger(tmp_path / "retry.sqlite3"),
        user_id="u1",
        session_id="s1",
        session_budget=2 * (input_bound + 7),
        daily_budget=2 * (input_bound + 7),
        throttle=True,
    )
    llm.set_budget_scope(scope)
    client = _Client(
        [
            _Response([], status=503),
            _Response(
                [
                    'data: {"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}',
                    "data: [DONE]",
                ]
            ),
        ]
    )
    with patch.object(llm, "_get_client", AsyncMock(return_value=client)):
        async for _event in llm.stream_chat(messages, None):
            pass

    assert [body["max_tokens"] for body in client.bodies] == [7, 7]
    totals = await scope.ledger.snapshot(user_id="u1", session_id="s1")
    assert totals.session_tokens == input_bound + 9
    await llm.close()


@pytest.mark.asyncio
async def test_cancelled_partial_stream_settles_known_usage_before_unwinding(tmp_path) -> None:
    messages = [{"role": "user", "content": "hello"}]
    input_bound = conservative_input_bound(messages, None)
    llm = LLMClient(
        ModelConfig(
            name="test",
            provider="openai_compat",
            base_url="https://provider.invalid",
            model="fixture",
            max_tokens=7,
        ),
        max_retries=1,
    )
    scope = ChatBudgetScope(
        ledger=ChatBudgetLedger(tmp_path / "cancel.sqlite3"),
        user_id="u1",
        session_id="s1",
        session_budget=input_bound + 7,
        daily_budget=input_bound + 7,
        throttle=True,
    )
    llm.set_budget_scope(scope)
    response = _BlockingResponse()
    client = _Client([response])

    async def consume() -> None:
        async for _event in llm.stream_chat(messages, None):
            pass

    with patch.object(llm, "_get_client", AsyncMock(return_value=client)):
        task = asyncio.create_task(consume())
        await response.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    totals = await scope.ledger.snapshot(user_id="u1", session_id="s1")
    assert totals.session_tokens == 2
    await llm.close()
