"""Trading strategy implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from thomas.marketplace.quantfin import indicators


@dataclass
class StrategySignal:
    """Trading signal with metadata.

    Attributes:
        timestamp: Signal timestamp
        asset: Asset symbol
        signal_type: 'BUY', 'SELL', or 'HOLD'
        strength: Signal strength (0.0 to 1.0)
        entry_price: Suggested entry price
        exit_price: Suggested exit price
        metadata: Additional data
    """

    timestamp: datetime
    asset: str
    signal_type: str
    strength: float = 0.5
    entry_price: float | None = None
    exit_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MeanReversionStrategy:
    """Mean reversion strategy using Bollinger Bands or z-score.

    Signals short when price is above upper band, long when below lower band.
    """

    def __init__(
        self,
        lookback: int = 20,
        num_std: float = 2.0,
        use_zscore: bool = False,
        zscore_threshold: float = 2.0,
    ) -> None:
        """Initialize mean reversion strategy.

        Args:
            lookback: Lookback period (default: 20)
            num_std: Number of standard deviations for Bollinger Bands
            use_zscore: Use z-score method instead of Bollinger Bands
            zscore_threshold: Z-score threshold for signals
        """
        self.lookback = lookback
        self.num_std = num_std
        self.use_zscore = use_zscore
        self.zscore_threshold = zscore_threshold

    def generate_signal(
        self,
        prices: np.ndarray,
        asset: str,
        timestamp: datetime,
    ) -> StrategySignal | None:
        """Generate mean reversion signal.

        Args:
            prices: Price series
            asset: Asset symbol
            timestamp: Current timestamp

        Returns:
            StrategySignal if signal generated, None otherwise
        """
        if len(prices) < self.lookback + 1:
            return None

        current_price = prices[-1]

        if self.use_zscore:
            mean = np.mean(prices[-self.lookback :])
            std = np.std(prices[-self.lookback :])

            if std == 0:
                return None

            zscore = (current_price - mean) / std

            if zscore < -self.zscore_threshold:
                return StrategySignal(
                    timestamp=timestamp,
                    asset=asset,
                    signal_type="BUY",
                    strength=min(abs(zscore) / (2 * self.zscore_threshold), 1.0),
                    entry_price=current_price,
                    exit_price=mean,
                    metadata={"zscore": zscore},
                )
            elif zscore > self.zscore_threshold:
                return StrategySignal(
                    timestamp=timestamp,
                    asset=asset,
                    signal_type="SELL",
                    strength=min(abs(zscore) / (2 * self.zscore_threshold), 1.0),
                    entry_price=current_price,
                    exit_price=mean,
                    metadata={"zscore": zscore},
                )
        else:
            upper, middle, lower = indicators.bollinger_bands(
                prices[-self.lookback :],
                self.lookback,
                self.num_std,
            )

            if len(upper) == 0:
                return None

            upper_val = upper[-1]
            lower_val = lower[-1]
            mid_val = middle[-1]

            if current_price < lower_val:
                strength = (lower_val - current_price) / (lower_val - mid_val + 1e-8)
                return StrategySignal(
                    timestamp=timestamp,
                    asset=asset,
                    signal_type="BUY",
                    strength=min(strength, 1.0),
                    entry_price=current_price,
                    exit_price=mid_val,
                    metadata={"bb_bands": (upper_val, mid_val, lower_val)},
                )
            elif current_price > upper_val:
                strength = (current_price - upper_val) / (mid_val - upper_val + 1e-8)
                return StrategySignal(
                    timestamp=timestamp,
                    asset=asset,
                    signal_type="SELL",
                    strength=min(strength, 1.0),
                    entry_price=current_price,
                    exit_price=mid_val,
                    metadata={"bb_bands": (upper_val, mid_val, lower_val)},
                )

        return None


class MomentumStrategy:
    """Trend-following momentum strategy using moving average crossovers.

    Generates BUY signal when fast MA crosses above slow MA (bullish).
    Generates SELL signal when fast MA crosses below slow MA (bearish).
    """

    def __init__(self, fast_period: int = 12, slow_period: int = 26) -> None:
        """Initialize momentum strategy.

        Args:
            fast_period: Fast moving average period
            slow_period: Slow moving average period
        """
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signal(
        self,
        prices: np.ndarray,
        asset: str,
        timestamp: datetime,
    ) -> StrategySignal | None:
        """Generate momentum signal.

        Args:
            prices: Price series
            asset: Asset symbol
            timestamp: Current timestamp

        Returns:
            StrategySignal if crossover detected
        """
        if len(prices) < self.slow_period + 1:
            return None

        fast_ma = indicators.ema(prices, self.fast_period)
        slow_ma = indicators.ema(prices, self.slow_period)

        if len(fast_ma) < 2 or len(slow_ma) < 2:
            return None

        # Check for crossover
        prev_diff = fast_ma[-2] - slow_ma[-2]
        curr_diff = fast_ma[-1] - slow_ma[-1]

        current_price = prices[-1]

        if prev_diff <= 0 and curr_diff > 0:  # Bullish crossover
            return StrategySignal(
                timestamp=timestamp,
                asset=asset,
                signal_type="BUY",
                strength=0.7,
                entry_price=current_price,
                exit_price=None,
                metadata={
                    "fast_ma": float(fast_ma[-1]),
                    "slow_ma": float(slow_ma[-1]),
                },
            )
        elif prev_diff >= 0 and curr_diff < 0:  # Bearish crossover
            return StrategySignal(
                timestamp=timestamp,
                asset=asset,
                signal_type="SELL",
                strength=0.7,
                entry_price=current_price,
                exit_price=None,
                metadata={
                    "fast_ma": float(fast_ma[-1]),
                    "slow_ma": float(slow_ma[-1]),
                },
            )

        return None


class PairsStrategy:
    """Pairs trading strategy using cointegration and z-score.

    Trades the spread between two cointegrated assets.
    """

    def __init__(self, lookback: int = 60, zscore_entry: float = 2.0) -> None:
        """Initialize pairs strategy.

        Args:
            lookback: Lookback period for spread calculation
            zscore_entry: Z-score threshold for entry signals
        """
        self.lookback = lookback
        self.zscore_entry = zscore_entry

    def calculate_spread(
        self,
        prices1: np.ndarray,
        prices2: np.ndarray,
        hedge_ratio: float = 1.0,
    ) -> np.ndarray:
        """Calculate spread between two price series.

        Args:
            prices1: First asset prices
            prices2: Second asset prices
            hedge_ratio: Hedge ratio for spread calculation

        Returns:
            Spread series
        """
        if len(prices1) != len(prices2):
            raise ValueError("Price series must be same length")

        return prices1 - hedge_ratio * prices2

    def generate_signal(
        self,
        spread: np.ndarray,
        asset1: str,
        asset2: str,
        timestamp: datetime,
    ) -> StrategySignal | None:
        """Generate pairs trading signal.

        Args:
            spread: Spread series
            asset1: First asset symbol
            asset2: Second asset symbol
            timestamp: Current timestamp

        Returns:
            StrategySignal if spread z-score exceeds threshold
        """
        if len(spread) < self.lookback:
            return None

        recent_spread = spread[-self.lookback :]
        mean_spread = np.mean(recent_spread)
        std_spread = np.std(recent_spread)

        if std_spread == 0:
            return None

        current_spread = spread[-1]
        zscore = (current_spread - mean_spread) / std_spread

        if zscore > self.zscore_entry:
            return StrategySignal(
                timestamp=timestamp,
                asset=f"{asset1}/{asset2}",
                signal_type="SELL",
                strength=min(abs(zscore) / (2 * self.zscore_entry), 1.0),
                metadata={
                    "zscore": zscore,
                    "spread": current_spread,
                    "mean_spread": mean_spread,
                },
            )
        elif zscore < -self.zscore_entry:
            return StrategySignal(
                timestamp=timestamp,
                asset=f"{asset1}/{asset2}",
                signal_type="BUY",
                strength=min(abs(zscore) / (2 * self.zscore_entry), 1.0),
                metadata={
                    "zscore": zscore,
                    "spread": current_spread,
                    "mean_spread": mean_spread,
                },
            )

        return None


class MarketMakingStrategy:
    """Market making strategy with inventory risk management.

    Quotes both sides of market around mid-price with spread based on
    volatility and inventory.
    """

    def __init__(
        self,
        base_spread: float = 0.01,
        inventory_limit: int = 100,
        volatility_multiplier: float = 1.0,
    ) -> None:
        """Initialize market making strategy.

        Args:
            base_spread: Base bid-ask spread (default: 1%)
            inventory_limit: Maximum inventory limit
            volatility_multiplier: Volatility impact on spread
        """
        self.base_spread = base_spread
        self.inventory_limit = inventory_limit
        self.volatility_multiplier = volatility_multiplier

    def calculate_quotes(
        self,
        mid_price: float,
        current_inventory: int,
        volatility: float,
    ) -> tuple[float, float]:
        """Calculate bid and ask quotes.

        Args:
            mid_price: Market mid price
            current_inventory: Current inventory position
            volatility: Current volatility

        Returns:
            Tuple of (bid_price, ask_price)
        """
        # Adjust spread based on volatility
        adjusted_spread = self.base_spread * (1 + self.volatility_multiplier * volatility)

        # Adjust prices based on inventory
        inventory_adjustment = (current_inventory / self.inventory_limit) * adjusted_spread

        bid_price = mid_price - adjusted_spread / 2 + inventory_adjustment
        ask_price = mid_price + adjusted_spread / 2 + inventory_adjustment

        return bid_price, ask_price


class StrategyComposer:
    """Combines multiple trading signals into composite signal.

    Weights and combines signals from different strategies.
    """

    def __init__(self) -> None:
        """Initialize strategy composer."""
        self.strategies: dict[str, tuple[Any, float]] = {}

    def add_strategy(self, name: str, strategy: Any, weight: float = 1.0) -> None:
        """Add strategy to composer.

        Args:
            name: Strategy name
            strategy: Strategy instance
            weight: Signal weight (default: 1.0)
        """
        self.strategies[name] = (strategy, weight)

    def generate_composite_signal(
        self,
        signals: dict[str, StrategySignal | None],
        timestamp: datetime,
        asset: str,
    ) -> StrategySignal | None:
        """Generate composite signal from multiple strategy signals.

        Args:
            signals: Dictionary of strategy name -> signal
            timestamp: Current timestamp
            asset: Asset symbol

        Returns:
            Composite StrategySignal or None
        """
        buy_strength = 0.0
        sell_strength = 0.0
        total_weight = 0.0
        all_metadata: dict[str, Any] = {}

        for name, (_, weight) in self.strategies.items():
            signal = signals.get(name)
            if signal is None:
                continue

            total_weight += weight

            if signal.signal_type == "BUY":
                buy_strength += signal.strength * weight
                all_metadata[f"{name}_buy"] = signal.strength
            elif signal.signal_type == "SELL":
                sell_strength += signal.strength * weight
                all_metadata[f"{name}_sell"] = signal.strength

        if total_weight == 0:
            return None

        buy_strength /= total_weight
        sell_strength /= total_weight

        if buy_strength > sell_strength and buy_strength > 0.5:
            return StrategySignal(
                timestamp=timestamp,
                asset=asset,
                signal_type="BUY",
                strength=buy_strength,
                metadata=all_metadata,
            )
        elif sell_strength > buy_strength and sell_strength > 0.5:
            return StrategySignal(
                timestamp=timestamp,
                asset=asset,
                signal_type="SELL",
                strength=sell_strength,
                metadata=all_metadata,
            )

        return None
