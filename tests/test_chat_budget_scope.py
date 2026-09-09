from __future__ import annotations

import asyncio
import time

import pytest

from thomas.core.config import ModelConfig
from thomas.core.llm_client import LLMClient
from thomas.core.llm_streaming_codex import _build_openai_codex_request
from thomas.server.chat_budget_ledger import ChatBudgetExceeded, ChatBudgetLedger
from thomas.server.chat_budget_scope import ChatBudgetScope, conservative_input_bound


@pytest.mark.asyncio
async def test_supported_provider_builders_receive_the_atomic_remaining_output_cap(tmp_path) -> None:
    messages = [{"role": "user", "content": "hello"}]
    input_bound = conservative_input_bound(messages, None)
    ledger = ChatBudgetLedger(tmp_path / "budget.sqlite3")
    scope = ChatBudgetScope(
        ledger=ledger,
        user_id="u1",
        session_id="s1",
        session_budget=input_bound + 7,
        daily_budget=input_bound + 7,
        throttle=True,
    )
    llm = LLMClient(
        ModelConfig(
            name="test",
            provider="openai_compat",
            base_url="http://127.0.0.1:1",
            model="fixture",
            max_tokens=100,
        )
    )
    llm.set_budget_scope(scope)

    attempt = await llm.begin_budget_attempt(messages, None)
    try:
        assert attempt.output_cap == 7
        assert llm._build_openai_request(messages, max_output_tokens=attempt.output_cap)["max_tokens"] == 7
        assert llm._build_anthropic_request(messages, max_output_tokens=attempt.output_cap)["max_tokens"] == 7
        assert "max_output_tokens" not in _build_openai_codex_request(llm, messages, None)
    finally:
        await attempt.scope.abort_attempt(attempt.lease)
        await llm.close()


@pytest.mark.asyncio
async def test_input_that_exhausts_remaining_budget_is_denied_before_provider_dispatch(tmp_path) -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "inspect this"},
                {"type": "image_url", "image_url": {"url": "https://example.com/large.png"}},
            ],
        }
    ]
    scope = ChatBudgetScope(
        ledger=ChatBudgetLedger(tmp_path / "budget.sqlite3"),
        user_id="u1",
        session_id="s1",
        session_budget=1_000,
        daily_budget=1_000,
        throttle=True,
    )
    llm = LLMClient(ModelConfig(name="test", provider="openai_compat", base_url="http://127.0.0.1:1", model="fixture"))
    llm.set_budget_scope(scope)

    with pytest.raises(ChatBudgetExceeded, match="cannot fit"):
        await llm.begin_budget_attempt(messages, None)
    assert (await scope.ledger.snapshot(user_id="u1", session_id="s1")).session_tokens == 0
    await llm.close()


@pytest.mark.asyncio
async def test_missing_provider_usage_is_charged_pessimistically(tmp_path) -> None:
    messages = [{"role": "user", "content": "hello"}]
    input_bound = conservative_input_bound(messages, None)
    scope = ChatBudgetScope(
        ledger=ChatBudgetLedger(tmp_path / "budget.sqlite3"),
        user_id="u1",
        session_id="s1",
        session_budget=input_bound + 9,
        daily_budget=input_bound + 9,
        throttle=True,
    )
    llm = LLMClient(ModelConfig(name="test", provider="openai_compat", base_url="http://127.0.0.1:1", model="fixture"))
    llm.set_budget_scope(scope)

    attempt = await llm.begin_budget_attempt(messages, None)
    await llm.finish_budget_attempt(attempt)

    totals = await scope.ledger.snapshot(user_id="u1", session_id="s1")
    assert totals.session_tokens == input_bound + 9
    assert totals.daily_tokens == input_bound + 9
    await llm.close()


@pytest.mark.asyncio
async def test_cancelled_preflight_releases_a_late_committed_reservation(tmp_path) -> None:
    class SlowLedger(ChatBudgetLedger):
        def _reserve_sync(self, **kwargs):  # noqa: ANN003, ANN202
            time.sleep(0.08)
            return super()._reserve_sync(**kwargs)

    ledger = SlowLedger(tmp_path / "budget.sqlite3")
    scope = ChatBudgetScope(
        ledger=ledger,
        user_id="u1",
        session_id="s1",
        session_budget=10,
        daily_budget=10,
        throttle=True,
    )
    preflight = asyncio.create_task(scope.preflight())
    await asyncio.sleep(0.01)
    preflight.cancel()

    with pytest.raises(asyncio.CancelledError):
        await preflight
    ticket = await ledger.reserve(
        user_id="u1",
        session_id="s1",
        prior_session_tokens=0,
        session_budget=10,
        daily_budget=10,
        throttle=True,
        estimated_tokens=10,
    )
    assert ticket.reserved_tokens == 10
