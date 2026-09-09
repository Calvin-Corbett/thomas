"""Tests for the training-simulator foundation: market data + replay broker.

Hermetic: builds synthetic bars and a pre-written cache, no network. The live
Yahoo fetch is exercised separately as a smoke check, not in the test suite.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import pytest

from thomas.marketplace.paper_trading._types import JournalEntry
from thomas.marketplace.paper_trading.engine import PaperTradingEngine
from thomas.marketplace.paper_trading.market_data import Bar, load_daily_bars
from thomas.marketplace.paper_trading.replay import ReplayBroker
from thomas.marketplace.paper_trading.store import PaperTradingStore


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_PAPER_TRADING_DIR", str(tmp_path))
    for var in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _rising_bars(n=120, start=100.0, step=0.5):
    out: list[Bar] = []
    d = date(2023, 1, 2)
    while len(out) < n:
        if d.weekday() < 5:  # weekdays only
            px = round(start + step * len(out), 2)
            out.append(
                Bar(
                    date=d.isoformat(),
                    open=px,
                    high=round(px * 1.01, 2),
                    low=round(px * 0.99, 2),
                    close=px,
                    volume=1000,
                )
            )
        d += timedelta(days=1)
    return out


# --- market data cache (hermetic) ------------------------------------------
def test_load_daily_bars_reads_cache_without_fetch(tmp_path):
    from thomas.marketplace.paper_trading.market_data import _cache_path

    bars = _rising_bars(10)
    path = _cache_path(tmp_path, "TEST", "5y")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([b.to_dict() for b in bars]), encoding="utf-8")

    loaded = load_daily_bars("TEST", cache_dir=tmp_path, allow_fetch=False)
    assert len(loaded) == 10
    assert loaded[0].close == bars[0].close


# --- replay broker ----------------------------------------------------------
def test_replay_no_lookahead_and_advance():
    broker = ReplayBroker({"TEST": _rising_bars(100)}, warmup=20)
    # On day 0 (cursor=20), only 21 bars are visible (indices 0..20).
    bars = run(broker.get_bars("TEST", limit=999))
    assert len(bars) == 21
    assert bars[-1]["t"] == broker.current_date()
    q0 = run(broker.get_latest_quote("TEST"))
    broker.advance()
    q1 = run(broker.get_latest_quote("TEST"))
    assert q1.price > q0.price  # rising series, time moved forward
    bars2 = run(broker.get_bars("TEST", limit=999))
    assert len(bars2) == 22  # exactly one more day visible


def test_replay_fill_updates_cash_and_position():
    broker = ReplayBroker({"TEST": _rising_bars(100)}, warmup=20, starting_cash=100_000)
    price = run(broker.get_latest_quote("TEST")).price
    order = run(
        broker.submit_order(
            symbol="TEST",
            side="buy",
            qty=10,
            notional=None,
            order_type="market",
            limit_price=None,
            time_in_force="day",
        )
    )
    assert order["status"] == "filled"
    acct = run(broker.get_account())
    assert acct.cash == pytest.approx(100_000 - 10 * price, abs=0.01)
    positions = run(broker.list_positions())
    assert positions and positions[0].symbol == "TEST"
    assert positions[0].qty == 10


def test_replay_buy_and_hold_benchmark_positive_for_rising_series():
    broker = ReplayBroker({"TEST": _rising_bars(100)}, warmup=10)
    assert broker.buy_and_hold_return_pct("TEST") > 0


def test_replay_is_done_at_end():
    broker = ReplayBroker({"TEST": _rising_bars(30)}, warmup=0)
    steps = 0
    while broker.advance():
        steps += 1
    assert broker.is_done()
    assert steps == 29  # 30 bars -> 29 advances


# --- engine drives a backtest unchanged (the key reuse) ---------------------
def test_engine_runs_a_trade_against_replay_broker(clean_env):
    from thomas.marketplace.paper_trading.config import load_paper_trading_config

    cfg = load_paper_trading_config()
    broker = ReplayBroker({"AAPL": _rising_bars(120)}, warmup=30)
    engine = PaperTradingEngine(cfg, PaperTradingStore(cfg.state_path), broker)

    proposal = run(
        engine.propose(
            symbol="AAPL",
            side="buy",
            thesis="uptrend in the replay window",
            invalidation="breaks the recent low",
            notional=500,
        )
    )
    assert proposal.status == "pending_approval", proposal.risk
    engine.approve(proposal.id)
    submitted = run(engine.submit(proposal.id))
    assert submitted.status in ("submitted", "filled")
    positions = run(engine.positions())
    assert any(p.symbol == "AAPL" for p in positions)


# --- coach (grading) --------------------------------------------------------
def test_max_drawdown_pct():
    from thomas.marketplace.paper_trading.coach import max_drawdown_pct

    curve = [{"equity": 100}, {"equity": 120}, {"equity": 90}, {"equity": 110}]
    # peak 120 -> trough 90 = 25% drawdown
    assert max_drawdown_pct(curve) == pytest.approx(25.0)


def test_grade_run_computes_alpha_and_letter():
    from thomas.marketplace.paper_trading.coach import grade_run

    journal = [
        JournalEntry(
            id="a",
            proposal_id="p",
            symbol="X",
            side="buy",
            qty=1,
            entry_price=10,
            thesis="t",
            invalidation="i",
            realized_pl=50,
            closed_at="2023-01-10T00:00:00Z",
            thesis_outcome="validated",
        ),
    ]
    grade = grade_run(
        scenario="test",
        symbol="X",
        starting_cash=1000.0,
        final_equity=1150.0,
        benchmark_return_pct=10.0,
        journal=journal,
        equity_curve=[{"equity": 1000}, {"equity": 1200}, {"equity": 1150}],
        risk_blocks=0,
    )
    assert grade.return_pct == pytest.approx(15.0)
    assert grade.alpha_pct == pytest.approx(5.0)  # 15% return - 10% benchmark
    assert grade.grade_letter in {"A", "B", "C", "D", "F"}
    assert grade.sandbox_caveat  # honesty note always present


# --- trainer (the auto loop) ------------------------------------------------
def test_run_training_rejects_live_broker(tmp_path):
    from thomas.marketplace.paper_trading._exceptions import PaperTradingError
    from thomas.marketplace.paper_trading.trainer import run_training

    class _LiveFake:
        is_simulated = False

    with pytest.raises(PaperTradingError):
        run(run_training(symbol="X", cache_dir=tmp_path, broker=_LiveFake()))


def test_run_training_end_to_end_on_seeded_cache(clean_env, tmp_path):
    from thomas.marketplace.paper_trading.market_data import _cache_path
    from thomas.marketplace.paper_trading.trainer import run_training

    # Seed the cache so no network is needed (rng default "2y").
    bars = _rising_bars(200)
    path = _cache_path(tmp_path, "TEST", "2y")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([b.to_dict() for b in bars]), encoding="utf-8")

    result = run(run_training(symbol="TEST", cache_dir=tmp_path, cadence_days=3))
    grade = result["grade"]
    assert result["days"] > 100
    assert grade["trades"] >= 1  # momentum should buy in a rising series
    assert grade["final_equity"] > 100_000  # made money riding the uptrend
    assert grade["grade_letter"] in {"A", "B", "C", "D", "F"}
    assert "lessons" in result and result["lessons"]["headline"]
    # Backtests must not pollute the live store.
    live_state = tmp_path / "state.json"
    assert not live_state.exists()
