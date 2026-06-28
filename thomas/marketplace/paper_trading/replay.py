"""Historical replay broker — the heart of the training simulator.

A ReplayBroker implements the same duck-typed async interface as AlpacaPaperClient
and SimBroker, but serves prices from real historical daily bars and a moving time
cursor. The Trader AI sees only data up to the current sim-day (NO look-ahead);
orders fill at that day's close; ``advance()`` steps to the next trading day.

Because it's just another broker, the existing PaperTradingEngine and agent tools
drive a backtest unchanged.
"""

from __future__ import annotations

import bisect
from typing import Any

from thomas.marketplace.paper_trading._types import (
    AccountSnapshot,
    PositionSnapshot,
    Quote,
    Side,
    new_id,
)
from thomas.marketplace.paper_trading.market_data import Bar


class ReplayBroker:
    """Deterministic backtest broker over historical daily bars.

    Args:
        bars_by_symbol: symbol -> chronological list[Bar]
        starting_cash: opening sim cash
        warmup: how many bars of history are visible before day 0 (so the Trader
            has something to analyze on the first decision).
    """

    is_simulated = True

    def __init__(
        self,
        bars_by_symbol: dict[str, list[Bar]],
        *,
        starting_cash: float = 100_000.0,
        warmup: int = 50,
    ) -> None:
        self._bars = {s.upper(): list(b) for s, b in bars_by_symbol.items()}
        # Per-symbol date index for fast "most recent bar <= date" lookups.
        self._dates = {s: [b.date for b in bars] for s, bars in self._bars.items()}
        timeline = sorted({d for ds in self._dates.values() for d in ds})
        if not timeline:
            raise ValueError("ReplayBroker requires at least one bar")
        self._timeline = timeline
        self._cursor = min(max(int(warmup), 0), len(timeline) - 1)
        self._starting_cash = float(starting_cash)
        self._cash = float(starting_cash)
        # symbol -> {"qty": float, "avg_entry_price": float}
        self._positions: dict[str, dict[str, float]] = {}

    # --- time control -------------------------------------------------------
    def current_date(self) -> str:
        return self._timeline[self._cursor]

    def is_done(self) -> bool:
        return self._cursor >= len(self._timeline) - 1

    def advance(self) -> bool:
        """Step to the next trading day. Returns False when the run is over."""
        if self.is_done():
            return False
        self._cursor += 1
        return True

    def progress(self) -> dict[str, Any]:
        return {
            "date": self.current_date(),
            "day": self._cursor + 1,
            "total_days": len(self._timeline),
            "done": self.is_done(),
        }

    # --- price lookups (no look-ahead) -------------------------------------
    def _bar_on_or_before(self, symbol: str, date: str) -> Bar | None:
        symbol = symbol.upper()
        dates = self._dates.get(symbol)
        if not dates:
            return None
        idx = bisect.bisect_right(dates, date) - 1
        if idx < 0:
            return None
        return self._bars[symbol][idx]

    def _price(self, symbol: str) -> float:
        bar = self._bar_on_or_before(symbol, self.current_date())
        return bar.close if bar else 0.0

    # --- broker interface ---------------------------------------------------
    async def get_latest_quote(self, symbol: str) -> Quote:
        price = self._price(symbol)
        return Quote(
            symbol=symbol.upper(),
            price=price,
            bid=round(price * 0.999, 4),
            ask=round(price * 1.001, 4),
            as_of=self.current_date(),
            feed="replay",
        )

    async def get_bars(self, symbol: str, *, timeframe: str = "1Day", limit: int = 30) -> list[dict[str, Any]]:
        symbol = symbol.upper()
        dates = self._dates.get(symbol)
        if not dates:
            return []
        end = bisect.bisect_right(dates, self.current_date())  # exclusive of future
        visible = self._bars[symbol][:end]
        window = visible[-int(limit) :] if limit else visible
        return [{"t": b.date, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume} for b in window]

    async def list_positions(self) -> list[PositionSnapshot]:
        out: list[PositionSnapshot] = []
        for symbol, pos in self._positions.items():
            qty = pos["qty"]
            if qty == 0:
                continue
            price = self._price(symbol)
            avg = pos["avg_entry_price"]
            out.append(
                PositionSnapshot(
                    symbol=symbol,
                    qty=qty,
                    avg_entry_price=avg,
                    current_price=price,
                    market_value=round(qty * price, 2),
                    unrealized_pl=round((price - avg) * qty, 2),
                    unrealized_plpc=round(((price - avg) / avg * 100.0) if avg else 0.0, 2),
                )
            )
        return out

    async def get_account(self) -> AccountSnapshot:
        invested = sum(p["qty"] * self._price(s) for s, p in self._positions.items() if p["qty"])
        equity = round(self._cash + invested, 2)
        return AccountSnapshot(
            equity=equity,
            cash=round(self._cash, 2),
            buying_power=round(max(self._cash, 0.0), 2),
            currency="USD",
            status="REPLAY",
            as_of=self.current_date(),
        )

    async def is_market_open(self) -> bool:
        return True  # every cursor position is, by construction, a trading day

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float | None,
        notional: float | None,
        order_type: str,
        limit_price: float | None,
        time_in_force: str,
    ) -> dict[str, Any]:
        symbol = (symbol or "").upper().strip()
        price = self._price(symbol)
        if price <= 0:
            return {"id": new_id("replay"), "status": "rejected", "reason": "no price"}
        fill_qty = float(qty) if qty else (float(notional) / price if notional else 0.0)
        signed = fill_qty if side == Side.BUY.value else -fill_qty
        pos = self._positions.setdefault(symbol, {"qty": 0.0, "avg_entry_price": price})
        new_qty = pos["qty"] + signed
        # Update weighted average entry only when increasing an existing direction.
        if pos["qty"] == 0 or (pos["qty"] > 0) == (signed > 0):
            total_cost = pos["avg_entry_price"] * abs(pos["qty"]) + price * abs(signed)
            denom = abs(new_qty) or 1.0
            pos["avg_entry_price"] = round(total_cost / denom, 4)
        pos["qty"] = round(new_qty, 6)
        self._cash -= signed * price  # buy reduces cash, sell adds
        return {
            "id": new_id("replay"),
            "status": "filled",
            "filled_avg_price": price,
            "filled_qty": fill_qty,
            "symbol": symbol,
            "side": side,
            "simulated": True,
            "as_of": self.current_date(),
        }

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return {"id": order_id, "status": "filled", "simulated": True}

    # --- benchmark helper for grading --------------------------------------
    def buy_and_hold_return_pct(self, symbol: str) -> float:
        """Return % of simply holding `symbol` from cursor-start to the end."""
        symbol = symbol.upper()
        bars = self._bars.get(symbol)
        if not bars:
            return 0.0
        start = self._bar_on_or_before(symbol, self._timeline[self._cursor])
        end = bars[-1]
        if not start or start.close <= 0:
            return 0.0
        return round((end.close - start.close) / start.close * 100.0, 2)
