"""The auto-trainer: runs a Trader through a historical scenario, then grades it.

Safety invariants:
* Auto-execution (propose -> approve -> submit with NO human tap) is allowed ONLY
  against a simulated/replay broker. ``_assert_sim`` enforces this so the auto
  loop can never place an unattended order on a live account.
* Each run uses its OWN store and writes coaching to a SEPARATE memory thread
  ("paper-trading-sim"), so backtests never pollute the live journal or the
  lessons the live Trader recalls.

The default Trader is a transparent momentum baseline so the harness is fast and
deterministic; an LLM-driven Trader can be supplied via the ``decide`` hook.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Callable

from thomas.marketplace.paper_trading._exceptions import (
    PaperTradingError,
    RiskRejected,
)
from thomas.marketplace.paper_trading._types import new_id
from thomas.marketplace.paper_trading.coach import (
    Grade,
    derive_lessons,
    grade_run,
)
from thomas.marketplace.paper_trading.config import load_paper_trading_config
from thomas.marketplace.paper_trading.engine import PaperTradingEngine
from thomas.marketplace.paper_trading.market_data import load_daily_bars
from thomas.marketplace.paper_trading.replay import ReplayBroker
from thomas.marketplace.paper_trading.store import PaperTradingStore

DecideFn = Callable[..., Awaitable[None]]


def _assert_sim(broker: Any) -> None:
    if not getattr(broker, "is_simulated", False):
        raise PaperTradingError("auto-training refuses to run on a live broker — simulated only")


async def _auto_execute(engine: PaperTradingEngine, **propose_kwargs: Any) -> None:
    """Propose + auto-approve + submit in ONE step. Sim-only by construction.

    ``engine.broker`` must be simulated (checked) — this is the only place that
    bypasses the human approval gate, and it is gated on that invariant.
    """
    _assert_sim(engine.broker)
    proposal = await engine.propose(**propose_kwargs)
    if proposal.status != "pending_approval":
        return  # blocked by risk or invalid — skip
    engine.approve(proposal.id, approver="sim-auto")
    await engine.submit(proposal.id)


async def momentum_decide(
    engine: PaperTradingEngine,
    broker: Any,
    *,
    symbol: str,
    sma: int = 20,
    cash_fraction: float = 0.25,
) -> None:
    """A transparent baseline Trader: buy above the N-day average, exit below it."""
    bars = await broker.get_bars(symbol, limit=sma + 5)
    closes = [b["c"] for b in bars]
    if len(closes) < sma:
        return
    avg = sum(closes[-sma:]) / sma
    price = closes[-1]
    positions = await engine.positions()
    holding = next((p.qty for p in positions if p.symbol == symbol.upper()), 0.0)

    try:
        if price > avg and holding <= 0:
            acct = await engine.account()
            notional = round(max(acct.cash, 0.0) * cash_fraction, 2)
            if notional >= 1:
                await _auto_execute(
                    engine,
                    symbol=symbol,
                    side="buy",
                    notional=notional,
                    thesis=f"price {price:.2f} above {sma}-day avg {avg:.2f} (momentum)",
                    invalidation=f"close falls below the {sma}-day average",
                )
        elif price < avg and holding > 0:
            await _auto_execute(
                engine,
                symbol=symbol,
                side="sell",
                qty=holding,
                thesis=f"price {price:.2f} below {sma}-day avg {avg:.2f} (exit)",
                invalidation="price reclaims the average",
            )
    except (RiskRejected, PaperTradingError):
        return


async def run_training(
    *,
    symbol: str,
    cache_dir: Path | str,
    rng: str = "2y",
    starting_cash: float = 100_000.0,
    cadence_days: int = 3,
    warmup: int = 30,
    decide: DecideFn | None = None,
    memory_engine: Any = None,
    scenario_name: str = "",
    broker: Any = None,
) -> dict[str, Any]:
    """Run one auto-training scenario end to end and return its grade.

    Pass ``broker`` to inject one (tests/advanced); otherwise a ReplayBroker is
    built from cached/fetched historical bars for ``symbol``.
    """
    if broker is None:
        bars = load_daily_bars(symbol, cache_dir=cache_dir, rng=rng)
        broker = ReplayBroker({symbol.upper(): bars}, warmup=warmup, starting_cash=starting_cash)
    _assert_sim(broker)

    cfg = load_paper_trading_config(data_dir=cache_dir)
    # Sim-tuned risk: keep the penny guard, but lift the live-trading guardrails
    # that don't apply to a backtest (daily-trade cap, per-order/position size).
    cfg.risk = replace(
        cfg.risk,
        max_trades_per_day=10_000_000,
        max_position_pct=100.0,
        max_order_usd=max(cfg.risk.max_order_usd, starting_cash * 0.5),
        regular_hours_only=False,
    )

    run_id = new_id("simrun")
    run_dir = Path(cache_dir) / "sim_runs" / run_id
    store = PaperTradingStore(run_dir / "state.json")
    # memory_engine=None on the engine: per-trade lessons are NOT written to live
    # memory during a backtest; the Coach writes one summary to the sim thread.
    engine = PaperTradingEngine(cfg, store, broker, memory_engine=None)
    decide = decide or momentum_decide

    equity_curve: list[dict[str, Any]] = []
    step = 0
    while True:
        if step % max(cadence_days, 1) == 0:
            try:
                await decide(engine, broker, symbol=symbol)
            except Exception:
                pass  # one bad decision day must not abort the whole run
        acct = await broker.get_account()
        equity_curve.append({"date": broker.current_date(), "equity": acct.equity})
        if not broker.advance():
            break
        step += 1

    await engine.reconcile()
    final_equity = (await broker.get_account()).equity
    benchmark = broker.buy_and_hold_return_pct(symbol)
    journal = store.list_journal()
    risk_blocks = len(store.list_proposals(status="blocked_by_risk"))
    grade: Grade = grade_run(
        scenario=scenario_name or symbol.upper(),
        symbol=symbol.upper(),
        starting_cash=starting_cash,
        final_equity=final_equity,
        benchmark_return_pct=benchmark,
        journal=journal,
        equity_curve=equity_curve,
        risk_blocks=risk_blocks,
    )
    lessons = derive_lessons(grade)

    if memory_engine is not None:
        try:
            add_event = getattr(memory_engine, "add_event", None)
            if callable(add_event):
                add_event(
                    "paper-trading-sim",
                    "coach_grade",
                    lessons.headline,
                    {"symbol": symbol.upper(), "alpha_pct": grade.alpha_pct, "grade": grade.grade_letter},
                )
        except Exception:
            pass

    return {
        "run_id": run_id,
        "scenario": scenario_name or symbol.upper(),
        "symbol": symbol.upper(),
        "days": len(equity_curve),
        "grade": grade.to_dict(),
        "lessons": lessons.to_dict(),
        "equity_curve": equity_curve,
    }
