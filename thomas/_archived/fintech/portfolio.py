"""
Portfolio management and valuation.

Handles position tracking, portfolio valuation, asset allocation tracking,
rebalancing, and performance attribution including time-weighted and
money-weighted returns.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ._types import Portfolio, Position


class PortfolioManager:
    """
    Manage portfolio positions and track performance.

    Handles position updates, valuation, asset allocation, and performance
    calculations including time-weighted and money-weighted returns.
    """

    def __init__(self, account_id: str, base_currency: str = "USD") -> None:
        """
        Initialize portfolio manager.

        Args:
            account_id: Account identifier
            base_currency: Base currency for portfolio
        """
        self.account_id = account_id
        self.base_currency = base_currency
        self.portfolio = Portfolio(
            account_id=account_id,
            currency=base_currency,
        )
        self.transaction_history: list[dict] = []

    def add_position(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
    ) -> None:
        """
        Add or update a position.

        Args:
            symbol: Trading symbol
            quantity: Number of units
            price: Price per unit
        """
        existing = self.portfolio.get_position(symbol)

        if existing is None:
            position = Position(
                symbol=symbol,
                quantity=quantity,
                avg_price=price,
                current_price=price,
            )
        else:
            # Update average price for buys
            if quantity > 0:
                total_cost = existing.quantity * existing.avg_price + quantity * price
                new_quantity = existing.quantity + quantity
                existing.avg_price = total_cost / new_quantity
                existing.quantity = new_quantity
            else:
                # Sell: reduce quantity, realize P&L
                existing.quantity += quantity
                profit = (price - existing.avg_price) * abs(quantity)
                existing.realized_pnl += profit

            existing.update_price(price)
            position = existing

        self.portfolio.add_position(position)
        self.transaction_history.append(
            {
                "timestamp": datetime.utcnow(),
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "type": "BUY" if quantity > 0 else "SELL",
            }
        )

    def close_position(self, symbol: str) -> Decimal:
        """
        Close entire position and return realized P&L.

        Args:
            symbol: Symbol to close

        Returns:
            Realized P&L from closing
        """
        position = self.portfolio.get_position(symbol)
        if position is None:
            return Decimal("0")

        pnl = position.realized_pnl + position.unrealized_pnl
        del self.portfolio.positions[symbol]
        return pnl

    def update_prices(self, prices: dict[str, Decimal]) -> None:
        """
        Update prices for multiple positions.

        Args:
            prices: Map of symbol to current price
        """
        for symbol, price in prices.items():
            position = self.portfolio.get_position(symbol)
            if position:
                position.update_price(price)

    def get_total_value(self) -> Decimal:
        """Get total portfolio value including cash."""
        return self.portfolio.get_total_market_value()

    def get_position_value(self, symbol: str) -> Decimal:
        """Get market value of a single position."""
        position = self.portfolio.get_position(symbol)
        if position is None:
            return Decimal("0")
        return position.get_market_value()

    def get_allocation(self) -> dict[str, Decimal]:
        """
        Get asset allocation as percentages.

        Returns:
            Map of symbol to allocation percentage
        """
        total_value = self.get_total_value()
        if total_value == 0:
            return {}

        return {
            symbol: (pos.get_market_value() / total_value * 100) for symbol, pos in self.portfolio.positions.items()
        }

    def get_performance_summary(self) -> dict[str, Decimal]:
        """
        Get performance metrics.

        Returns:
            Dictionary with realized P&L, unrealized P&L, total P&L, return %
        """
        total_value = self.get_total_value()
        cost_basis = self.portfolio.get_total_cost_basis()
        realized_pnl = self.portfolio.get_total_realized_pnl()
        unrealized_pnl = self.portfolio.get_total_unrealized_pnl()
        total_pnl = self.portfolio.get_total_pnl()

        return_pct = (total_pnl / cost_basis * 100) if cost_basis > 0 else Decimal("0")

        return {
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": total_pnl,
            "return_pct": return_pct,
            "total_value": total_value,
        }

    def calculate_rebalance_trades(
        self,
        target_allocation: dict[str, Decimal],
    ) -> dict[str, Decimal]:
        """
        Calculate trades needed to rebalance to target allocation.

        Args:
            target_allocation: Map of symbol to target allocation percentage

        Returns:
            Map of symbol to quantity to trade (positive=buy, negative=sell)
        """
        total_value = self.get_total_value()
        if total_value == 0:
            return {}

        trades: dict[str, Decimal] = {}

        for symbol, target_pct in target_allocation.items():
            target_value = total_value * (target_pct / 100)
            position = self.portfolio.get_position(symbol)

            if position:
                current_value = position.get_market_value()
                diff = target_value - current_value
            else:
                diff = target_value

            if diff != 0 and position:
                trades[symbol] = diff / position.current_price

        return trades

    def estimate_rebalance_cost(
        self,
        trades: dict[str, Decimal],
        fee_rate: Decimal = Decimal("0.001"),
    ) -> Decimal:
        """
        Estimate cost of rebalancing trades.

        Args:
            trades: Trades to estimate
            fee_rate: Fee rate as decimal (e.g., 0.001 for 0.1%)

        Returns:
            Total estimated fee cost
        """
        total_cost = Decimal("0")

        for symbol, qty in trades.items():
            position = self.portfolio.get_position(symbol)
            if position:
                notional = abs(qty) * position.current_price
                total_cost += notional * fee_rate

        return total_cost


class PerformanceCalculator:
    """
    Calculate portfolio returns and performance metrics.

    Supports time-weighted returns (TWR), money-weighted returns (MWR/IRR),
    and performance attribution.
    """

    @staticmethod
    def calculate_time_weighted_return(
        period_returns: list[Decimal],
    ) -> Decimal:
        """
        Calculate time-weighted return.

        TWR = (1 + R1) * (1 + R2) * ... * (1 + Rn) - 1

        Args:
            period_returns: List of period returns as decimals

        Returns:
            Time-weighted return
        """
        if not period_returns:
            return Decimal("0")

        twr = Decimal("1")
        for ret in period_returns:
            twr *= 1 + ret

        return twr - 1

    @staticmethod
    def calculate_money_weighted_return(
        initial_value: Decimal,
        final_value: Decimal,
        cash_flows: list[tuple[int, Decimal]],
    ) -> Decimal:
        """
        Calculate money-weighted return (IRR).

        Approximates IRR using cash flows at different time periods.

        Args:
            initial_value: Initial portfolio value
            final_value: Final portfolio value
            cash_flows: List of (days_elapsed, amount) tuples

        Returns:
            Approximate money-weighted return
        """
        if initial_value == 0:
            return Decimal("0")

        # Simplified IRR calculation using weighted cash flows
        total_invested = initial_value + sum(amount for _, amount in cash_flows)

        if total_invested == 0:
            return Decimal("0")

        gain = final_value - total_invested
        return gain / total_invested

    @staticmethod
    def calculate_return_attribution(
        position_returns: dict[str, Decimal],
        position_weights: dict[str, Decimal],
    ) -> dict[str, Decimal]:
        """
        Calculate performance attribution by position.

        Args:
            position_returns: Map of symbol to return
            position_weights: Map of symbol to portfolio weight

        Returns:
            Map of symbol to contribution to return
        """
        contribution = {}

        for symbol, ret in position_returns.items():
            weight = position_weights.get(symbol, Decimal("0"))
            contribution[symbol] = ret * weight

        return contribution

    @staticmethod
    def calculate_sector_return(
        positions: dict[str, tuple[Decimal, str]],
    ) -> dict[str, Decimal]:
        """
        Calculate returns by sector.

        Args:
            positions: Map of symbol to (return, sector) tuple

        Returns:
            Map of sector to average return
        """
        sector_returns: dict[str, list[Decimal]] = {}

        for symbol, (ret, sector) in positions.items():
            if sector not in sector_returns:
                sector_returns[sector] = []
            sector_returns[sector].append(ret)

        return {sector: sum(returns) / len(returns) for sector, returns in sector_returns.items()}

    @staticmethod
    def calculate_diversification_score(
        allocation: dict[str, Decimal],
    ) -> Decimal:
        """
        Calculate portfolio diversification score (0-1).

        Based on Herfindahl-Hirschman Index.

        Args:
            allocation: Map of symbol to allocation percentage

        Returns:
            Diversification score (1 = perfectly diversified)
        """
        if not allocation:
            return Decimal("0")

        # Normalize to 0-1 scale
        weights = [pct / 100 for pct in allocation.values()]
        hhi = sum(w**2 for w in weights)

        # HHI ranges from 1/n (perfectly diversified) to 1 (concentrated)
        n = len(allocation)
        max_hhi = Decimal("1")
        min_hhi = Decimal("1") / n

        if max_hhi == min_hhi:
            return Decimal("1")

        diversification = (max_hhi - hhi) / (max_hhi - min_hhi)
        return max(Decimal("0"), min(diversification, Decimal("1")))
