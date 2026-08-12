from __future__ import annotations

import asyncio
import json
import multiprocessing

import pytest

from thomas.server.chat_budget_ledger import ChatBudgetError, ChatBudgetExceeded, ChatBudgetLedger


def _reserve_and_settle_in_spawned_process(path, session_id, actual, ready, release, result) -> None:  # noqa: ANN001
    async def _run() -> None:
        ledger = ChatBudgetLedger(path)
        ticket = await ledger.reserve(
            user_id="u1",
            session_id=session_id,
            prior_session_tokens=0,
            session_budget=0,
            daily_budget=100,
            throttle=True,
            estimated_tokens=60,
        )
        ready.put(ticket.reserved_tokens)
        if not release.wait(15):
            raise RuntimeError("parent did not release budget worker")
        await ledger.settle(ticket, actual)
        result.put("settled")

    asyncio.run(_run())


@pytest.mark.asyncio
async def test_budget_ledger_serializes_reservations_and_settles_actual_usage(tmp_path) -> None:
    ledger = ChatBudgetLedger(tmp_path / "budget.json")
    first = await ledger.reserve(
        user_id="u1",
        session_id="s1",
        prior_session_tokens=0,
        session_budget=100,
        daily_budget=200,
        throttle=True,
        estimated_tokens=100,
    )
    with pytest.raises(ChatBudgetExceeded):
        await ledger.reserve(
            user_id="u1",
            session_id="s1",
            prior_session_tokens=0,
            session_budget=100,
            daily_budget=200,
            throttle=True,
            estimated_tokens=100,
        )

    totals = await ledger.settle(first, 8)
    assert totals.session_tokens == 8
    assert totals.daily_tokens == 8
    second = await ledger.reserve(
        user_id="u1",
        session_id="s1",
        prior_session_tokens=0,
        session_budget=100,
        daily_budget=200,
        throttle=True,
        estimated_tokens=100,
    )
    assert second.reserved_tokens == 92


@pytest.mark.asyncio
async def test_daily_budget_is_shared_across_sessions_and_persisted(tmp_path) -> None:
    path = tmp_path / "budget.json"
    ledger = ChatBudgetLedger(path)
    ticket = await ledger.reserve(
        user_id="u1",
        session_id="s1",
        prior_session_tokens=0,
        session_budget=0,
        daily_budget=10,
        throttle=True,
        estimated_tokens=10,
    )
    await ledger.settle(ticket, 10)

    reloaded = ChatBudgetLedger(path)
    with pytest.raises(ChatBudgetExceeded):
        await reloaded.reserve(
            user_id="u1",
            session_id="s2",
            prior_session_tokens=0,
            session_budget=0,
            daily_budget=10,
            throttle=True,
            estimated_tokens=1,
        )


@pytest.mark.asyncio
async def test_corrupt_budget_ledger_fails_closed(tmp_path) -> None:
    path = tmp_path / "budget.json"
    path.write_text(json.dumps([]), encoding="utf-8")
    ledger = ChatBudgetLedger(path)

    with pytest.raises(ChatBudgetError, match="unavailable"):
        await ledger.reserve(
            user_id="u1",
            session_id="s1",
            prior_session_tokens=0,
            session_budget=10,
            daily_budget=10,
            throttle=True,
            estimated_tokens=1,
        )


@pytest.mark.asyncio
async def test_independent_ledgers_cannot_overreserve_or_lose_settlements(tmp_path) -> None:
    path = tmp_path / "budget.sqlite3"
    first = ChatBudgetLedger(path)
    second = ChatBudgetLedger(path)

    outcomes = await asyncio.gather(
        first.reserve(
            user_id="u1",
            session_id="a",
            prior_session_tokens=0,
            session_budget=0,
            daily_budget=100,
            throttle=True,
            estimated_tokens=60,
        ),
        second.reserve(
            user_id="u1",
            session_id="b",
            prior_session_tokens=0,
            session_budget=0,
            daily_budget=100,
            throttle=True,
            estimated_tokens=60,
        ),
    )
    assert sorted(ticket.reserved_tokens for ticket in outcomes) == [40, 60]
    await asyncio.gather(first.settle(outcomes[0], 8), second.settle(outcomes[1], 7))

    assert (await ChatBudgetLedger(path).snapshot(user_id="u1", session_id="a")).daily_tokens == 15


def test_spawned_windows_processes_share_atomic_reservations(tmp_path) -> None:
    path = str(tmp_path / "budget.sqlite3")
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    result = context.Queue()
    release = context.Event()
    processes = [
        context.Process(
            target=_reserve_and_settle_in_spawned_process,
            args=(path, session_id, actual, ready, release, result),
        )
        for session_id, actual in (("a", 8), ("b", 7))
    ]
    try:
        for process in processes:
            process.start()
        reserved = sorted(ready.get(timeout=20) for _ in processes)
        assert reserved == [40, 60]
        release.set()
        assert [result.get(timeout=20) for _ in processes] == ["settled", "settled"]
    finally:
        release.set()
        for process in processes:
            process.join(timeout=20)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert [process.exitcode for process in processes] == [0, 0]
    totals = asyncio.run(ChatBudgetLedger(path).snapshot(user_id="u1", session_id="a"))
    assert totals.daily_tokens == 15


@pytest.mark.asyncio
async def test_provider_overrun_is_debited_then_blocks_future_calls(tmp_path) -> None:
    ledger = ChatBudgetLedger(tmp_path / "budget.sqlite3")
    ticket = await ledger.reserve(
        user_id="u1",
        session_id="s1",
        prior_session_tokens=0,
        session_budget=10,
        daily_budget=10,
        throttle=True,
        estimated_tokens=100,
    )

    with pytest.raises(ChatBudgetExceeded, match="Provider exceeded"):
        await ledger.settle(ticket, 40)
    with pytest.raises(ChatBudgetExceeded, match="Provider exceeded"):
        await ledger.settle(ticket, 40)
    totals = await ledger.snapshot(user_id="u1", session_id="s1")
    assert totals.session_tokens == 40
    assert totals.daily_tokens == 40
    with pytest.raises(ChatBudgetExceeded, match="Token budget exceeded"):
        await ledger.reserve(
            user_id="u1",
            session_id="s1",
            prior_session_tokens=0,
            session_budget=10,
            daily_budget=10,
            throttle=True,
            estimated_tokens=1,
        )


@pytest.mark.asyncio
async def test_session_budget_is_namespaced_by_user(tmp_path) -> None:
    ledger = ChatBudgetLedger(tmp_path / "budget.sqlite3")
    alice = await ledger.reserve(
        user_id="alice",
        session_id="shared",
        prior_session_tokens=0,
        session_budget=10,
        daily_budget=0,
        throttle=True,
        estimated_tokens=10,
    )
    await ledger.settle(alice, 10)

    bob = await ledger.reserve(
        user_id="bob",
        session_id="shared",
        prior_session_tokens=0,
        session_budget=10,
        daily_budget=0,
        throttle=True,
        estimated_tokens=1,
    )
    assert bob.reserved_tokens == 1
