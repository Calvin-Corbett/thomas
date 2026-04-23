"""Event-driven backtesting engine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from thomas.marketplace.quantfin._types import OHLCV, Asset, Order, OrderSide, Trade


@dataclass
class BacktestConfig:
    """Backtesting configuration.

    Attributes:
        initial_cash: Starting capital
        commission_rate: Commission as percentage of trade value
        slippage_bps: Slippage in basis points
        margin_multiplier: Leverage multiplier (default: 1.0 = no margin)
        max_positions: Maximum number of concurrent positions
    """

    initial_cash: float = 100000.0
    commission_rate: float = 0.001
    slippage_bps: float = 5.0
    margin_multiplier: float = 1.0
    max_positions: int = 100


@dataclass
class BacktestMetrics:
    """Backtest performance metrics.

    Attributes:
        total_return: Total return percentage
        annual_return: Annualized return
        sharpe_ratio: Sharpe ratio
        sortino_ratio: Sortino ratio
        calmar_ratio: Calmar ratio
        max_drawdown: Maximum drawdown
        win_rate: Winning trades / total trades
        profit_factor: Gross profit / gross loss
        num_trades: Total number of trades
        trades: List of executed trades
    """

    total_return: float
    annual_return: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    num_trades: int
    trades: list[Trade]


class BacktestEngine:
    """Event-driven backtesting engine.

    Simulates trading based on price data and signal generation.
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        """Initialize backtesting engine.

        Args:
            config: BacktestConfig (default: standard config)
        """
        self.config = config or BacktestConfig()
        self.cash = self.config.initial_cash
        self.positions: dict[str, float] = {}
        self.trades: list[Trade] = []
        self.portfolio_values: list[float] = []
        self.timestamps: list[datetime] = []
        self.orders: dict[str, Order] = {}

    def apply_slippage(self, price: float, side: OrderSide) -> float:
        """Apply slippage to execution price.

        Args:
            price: Quoted price
            side: Order side

        Returns:
            Slipped price
        """
        slippage = price * (self.config.slippage_bps / 10000.0)
        if side == OrderSide.BUY:
            return price + slippage
        else:
            return price - slippage

    def process_order(
        self,
        asset: Asset,
        side: OrderSide,
        quantity: float,
        price: float,
        timestamp: datetime,
    ) -> Trade | None:
        """Process market order.

        Args:
            asset: Asset to trade
            side: Buy or Sell
            quantity: Quantity to trade
            price: Market price
            timestamp: Trade timestamp

        Returns:
            Executed trade or None if insufficient cash/position
        """
        # Apply slippage
        execution_price = self.apply_slippage(price, side)

        # Calculate costs
        gross_value = quantity * execution_price
        commission = gross_value * self.config.commission_rate

        if side == OrderSide.BUY:
            if self.cash < gross_value + commission:
                return None  # Insufficient cash

            self.cash -= gross_value + commission
            current_qty = self.positions.get(asset.symbol, 0.0)
            self.positions[asset.symbol] = current_qty + quantity
        else:  # SELL
            current_qty = self.positions.get(asset.symbol, 0.0)
            if current_qty < quantity:
                return None  # Insufficient position

            self.cash += gross_value - commission
            self.positions[asset.symbol] = current_qty - quantity
            if self.positions[asset.symbol] == 0:
                del self.positions[asset.symbol]

        # Record trade
        trade = Trade(
            asset=asset,
            side=side,
            quantity=quantity,
            price=execution_price,
            timestamp=timestamp,
            commission=commission,
            slippage=abs(execution_price - price),
        )
        self.trades.append(trade)

        return trade

    def calculate_portfolio_value(self, price_dict: dict[str, float]) -> float:
        """Calculate current portfolio value.

        Args:
            price_dict: Dictionary of asset symbol -> price

        Returns:
            Total portfolio value (cash + positions)
        """
        position_value = 0.0
        for symbol, quantity in self.positions.items():
            if symbol in price_dict:
                position_value += quantity * price_dict[symbol]

        return self.cash + position_value

    def run_backtest(
        self,
        data: dict[str, list[OHLCV]],
        signal_generator: Callable[[dict[str, list[OHLCV]], datetime], dict[str, tuple[str, float]]],
    ) -> BacktestMetrics:
        """Run backtest simulation.

        Args:
            data: Dictionary of symbol -> list of OHLCV bars
            signal_generator: Function generating signals from price data

        Returns:
            BacktestMetrics with performance results
        """
        symbols = list(data.keys())
        all_dates = sorted(set(bar.timestamp for bars in data.values() for bar in bars))

        self.portfolio_values = []
        self.timestamps = []

        for date in all_dates:
            # Get current prices
            price_dict = {}
            for symbol in symbols:
                bars = [b for b in data[symbol] if b.timestamp == date]
                if bars:
                    price_dict[symbol] = bars[0].close

            # Generate signals
            try:
                signals = signal_generator(data, date)
            except Exception:
                signals = {}

            # Process signals
            for symbol, (signal_type, confidence) in signals.items():
                if symbol not in price_dict:
                    continue

                price = price_dict[symbol]

                if signal_type == "BUY":
                    # Calculate position size (simple: equal weight)
                    position_size = (self.cash * 0.1) / price  # 10% risk per trade
                    self.process_order(
                        Asset(symbol=symbol, name=symbol, asset_type="EQUITY"),
                        OrderSide.BUY,
                        position_size,
                        price,
                        date,
                    )
                elif signal_type == "SELL":
                    current_qty = self.positions.get(symbol, 0.0)
                    if current_qty > 0:
                        self.process_order(
                            Asset(symbol=symbol, name=symbol, asset_type="EQUITY"),
                            OrderSide.SELL,
                            current_qty,
                            price,
                            date,
                        )

            # Record portfolio value
            pv = self.calculate_portfolio_value(price_dict)
            self.portfolio_values.append(pv)
            self.timestamps.append(date)

        return self._calculate_metrics()

    def _calculate_metrics(self) -> BacktestMetrics:
        """Calculate backtest performance metrics.

        Returns:
            BacktestMetrics with results
        """
        if not self.portfolio_values:
            raise ValueError("No backtest data")

        pv = np.array(self.portfolio_values)
        returns = np.diff(pv) / pv[:-1]

        # Returns metrics
        total_return = (pv[-1] - pv[0]) / pv[0]
        num_days = len(pv) - 1
        annual_return = (1 + total_return) ** (252 / max(num_days, 1)) - 1

        # Risk metrics
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        sharpe = (mean_return * 252 - 0.02) / (std_return * np.sqrt(252)) if std_return > 0 else 0.0

        # Sortino ratio
        downside_returns = returns[returns < 0]
        downside_std = np.sqrt(np.mean(downside_returns**2)) if len(downside_returns) > 0 else 0.0
        sortino = (mean_return * 252 - 0.02) / (downside_std * np.sqrt(252)) if downside_std > 0 else 0.0

        # Drawdown
        cummax = np.maximum.accumulate(pv)
        drawdown = (pv - cummax) / cummax
        max_drawdown = np.min(drawdown)

        # Calmar ratio
        calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0.0

        # Trade statistics
        num_trades = len(self.trades)
        if num_trades > 0:
            pnls = [
                t.quantity * (t.price - self.trades[i - 1].price)
                if i > 0 and self.trades[i - 1].side == OrderSide.BUY and t.side == OrderSide.SELL
                else 0.0
                for i, t in enumerate(self.trades)
            ]
            winning_trades = sum(1 for pnl in pnls if pnl > 0)
            win_rate = winning_trades / num_trades

            gross_profit = sum(pnl for pnl in pnls if pnl > 0)
            gross_loss = sum(-pnl for pnl in pnls if pnl < 0)
            profit_factor = gross_profit / gross_loss if gross_loss != 0 else 0.0
        else:
            win_rate = 0.0
            profit_factor = 0.0

        return BacktestMetrics(
            total_return=total_return,
            annual_return=annual_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            num_trades=num_trades,
            trades=self.trades,
        )


class WalkForwardOptimizer:
    """Walk-forward optimization for strategy parameters.

    Performs rolling train/test windows with parameter optimization.
    """

    def __init__(
        self,
        train_period: int = 252,
        test_period: int = 63,
        step: int = 63,
    ) -> None:
        """Initialize walk-forward optimizer.

        Args:
            train_period: Training period in days
            test_period: Testing period in days
            step: Step size for rolling window
        """
        self.train_period = train_period
        self.test_period = test_period
        self.step = step

    def optimize(
        self,
        data: dict[str, list[OHLCV]],
        param_ranges: dict[str, list[Any]],
        signal_generator: Callable,
        evaluate_func: Callable,
    ) -> list[dict[str, Any]]:
        """Run walk-forward optimization.

        Args:
            data: Historical OHLCV data
            param_ranges: Parameter ranges to optimize
            signal_generator: Signal generation function
            evaluate_func: Function to evaluate parameters

        Returns:
            List of results for each walk-forward window
        """
        all_dates = sorted(set(bar.timestamp for bars in data.values() for bar in bars))
        results = []

        for i in range(0, len(all_dates) - self.train_period - self.test_period, self.step):
            train_end = i + self.train_period
            test_end = train_end + self.test_period

            train_dates = all_dates[i:train_end]
            test_dates = all_dates[train_end:test_end]

            # Find best parameters on training set
            best_params = None
            best_score = -float("inf")

            # Grid search (simplified)
            for params in self._generate_param_combinations(param_ranges):
                score = evaluate_func(data, train_dates, params, signal_generator)
                if score > best_score:
                    best_score = score
                    best_params = params

            # Test on test set
            test_score = evaluate_func(data, test_dates, best_params, signal_generator)

            results.append(
                {
                    "train_period": (train_dates[0], train_dates[-1]),
                    "test_period": (test_dates[0], test_dates[-1]),
                    "params": best_params,
                    "train_score": best_score,
                    "test_score": test_score,
                }
            )

        return results

    def _generate_param_combinations(self, param_ranges: dict[str, list[Any]]) -> list[dict[str, Any]]:
        """Generate all parameter combinations.

        Args:
            param_ranges: Parameter ranges

        Returns:
            List of parameter dictionaries
        """
        if not param_ranges:
            return [{}]

        keys = list(param_ranges.keys())
        combinations = []

        def generate(idx: int, current: dict[str, Any]) -> None:
            if idx == len(keys):
                combinations.append(current.copy())
                return

            key = keys[idx]
            for value in param_ranges[key]:
                current[key] = value
                generate(idx + 1, current)

        generate(0, {})
        return combinations


def monte_carlo_permutation_test(
    returns: np.ndarray,
    num_simulations: int = 1000,
) -> float:
    """Perform Monte Carlo permutation test for strategy significance.

    Tests if strategy returns are statistically significant vs random.

    Args:
        returns: Strategy return series
        num_simulations: Number of permutations

    Returns:
        P-value for significance test
    """
    actual_return = np.sum(returns)
    count_better = 0

    for _ in range(num_simulations):
        permuted = np.random.permutation(returns)
        if np.sum(permuted) >= actual_return:
            count_better += 1

    p_value = count_better / num_simulations
    return p_value
