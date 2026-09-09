"""
Risk management and measurement.

Implements portfolio risk calculations including Value at Risk, Expected Shortfall,
performance ratios (Sharpe, Sortino), drawdown analysis, beta calculation, and
position sizing using the Kelly criterion.
"""

from __future__ import annotations

import math
from decimal import Decimal

from scipy import stats

from ._exceptions import RiskLimitError
from ._types import Portfolio, Position


class RiskCalculator:
    """
    Calculate portfolio risk metrics including VaR, CVaR, and performance ratios.

    Supports multiple VaR calculation methods: historical simulation,
    parametric (variance-covariance), and Monte Carlo.
    """

    @staticmethod
    def calculate_historical_var(
        returns: list[Decimal],
        confidence: Decimal = Decimal("0.95"),
    ) -> Decimal:
        """
        Calculate Value at Risk using historical simulation.

        Args:
            returns: List of historical returns (as decimals)
            confidence: Confidence level (e.g., 0.95 for 95%)

        Returns:
            VaR estimate (negative value)
        """
        if not returns:
            return Decimal("0")

        sorted_returns = sorted([float(r) for r in returns])
        index = int(len(sorted_returns) * (1 - float(confidence)))
        index = max(0, min(index, len(sorted_returns) - 1))

        return Decimal(str(sorted_returns[index]))

    @staticmethod
    def calculate_parametric_var(
        mean_return: Decimal,
        volatility: Decimal,
        confidence: Decimal = Decimal("0.95"),
        position_value: Decimal = Decimal("1"),
    ) -> Decimal:
        """
        Calculate VaR using variance-covariance method.

        Args:
            mean_return: Mean return
            volatility: Standard deviation of returns
            confidence: Confidence level
            position_value: Position notional value

        Returns:
            VaR estimate (negative value)
        """
        z_score = float(stats.norm.ppf(1 - float(confidence)))
        var = mean_return - z_score * volatility
        return position_value * var

    @staticmethod
    def calculate_monte_carlo_var(
        mean_return: Decimal,
        volatility: Decimal,
        confidence: Decimal = Decimal("0.95"),
        simulations: int = 10000,
        periods: int = 1,
        position_value: Decimal = Decimal("1"),
    ) -> Decimal:
        """
        Calculate VaR using Monte Carlo simulation.

        Args:
            mean_return: Mean return
            volatility: Standard deviation
            confidence: Confidence level
            simulations: Number of simulations
            periods: Number of periods to simulate
            position_value: Position notional value

        Returns:
            VaR estimate (negative value)
        """
        import random

        random.seed(42)  # Reproducible results
        simulated_returns: list[float] = []

        for _ in range(simulations):
            period_return = float(mean_return)
            for _ in range(periods):
                shock = random.gauss(0, 1)
                period_return += float(volatility) * shock
            simulated_returns.append(period_return)

        var = RiskCalculator.calculate_historical_var(
            [Decimal(str(r)) for r in simulated_returns],
            confidence,
        )
        return position_value * var

    @staticmethod
    def calculate_cvar(
        returns: list[Decimal],
        confidence: Decimal = Decimal("0.95"),
    ) -> Decimal:
        """
        Calculate Conditional Value at Risk (Expected Shortfall).

        Args:
            returns: List of historical returns
            confidence: Confidence level

        Returns:
            CVaR estimate (negative value)
        """
        if not returns:
            return Decimal("0")

        var = RiskCalculator.calculate_historical_var(returns, confidence)
        worse_returns = [r for r in returns if r <= var]

        if not worse_returns:
            return var

        return sum(worse_returns) / len(worse_returns)

    @staticmethod
    def calculate_sharpe_ratio(
        returns: list[Decimal],
        risk_free_rate: Decimal = Decimal("0.02"),
    ) -> Decimal:
        """
        Calculate Sharpe ratio.

        Args:
            returns: List of periodic returns
            risk_free_rate: Risk-free rate (annual)

        Returns:
            Sharpe ratio
        """
        if not returns or len(returns) < 2:
            return Decimal("0")

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = variance.sqrt() if isinstance(variance, Decimal) else Decimal(str(math.sqrt(float(variance))))

        if std_dev == 0:
            return Decimal("0")

        excess_return = mean_return - (risk_free_rate / len(returns))
        return excess_return / std_dev

    @staticmethod
    def calculate_sortino_ratio(
        returns: list[Decimal],
        risk_free_rate: Decimal = Decimal("0.02"),
    ) -> Decimal:
        """
        Calculate Sortino ratio (downside risk focus).

        Args:
            returns: List of periodic returns
            risk_free_rate: Risk-free rate

        Returns:
            Sortino ratio
        """
        if not returns:
            return Decimal("0")

        mean_return = sum(returns) / len(returns)
        downside_returns = [r for r in returns if r < risk_free_rate / len(returns)]

        if not downside_returns:
            return Decimal("100")  # Perfect score if no downside

        downside_variance = sum((r - risk_free_rate / len(returns)) ** 2 for r in downside_returns) / len(returns)
        downside_std = Decimal(str(math.sqrt(float(downside_variance))))

        if downside_std == 0:
            return Decimal("0")

        excess_return = mean_return - (risk_free_rate / len(returns))
        return excess_return / downside_std

    @staticmethod
    def calculate_maximum_drawdown(returns: list[Decimal]) -> Decimal:
        """
        Calculate maximum drawdown.

        Args:
            returns: List of periodic returns

        Returns:
            Maximum drawdown (negative value)
        """
        if not returns:
            return Decimal("0")

        cumulative = [Decimal("1")]
        for ret in returns:
            cumulative.append(cumulative[-1] * (1 + ret))

        peak = cumulative[0]
        max_drawdown = Decimal("0")

        for value in cumulative:
            if value > peak:
                peak = value
            drawdown = (value - peak) / peak
            if drawdown < max_drawdown:
                max_drawdown = drawdown

        return max_drawdown

    @staticmethod
    def calculate_volatility(returns: list[Decimal]) -> Decimal:
        """
        Calculate portfolio volatility (standard deviation of returns).

        Args:
            returns: List of periodic returns

        Returns:
            Volatility (standard deviation)
        """
        if not returns or len(returns) < 2:
            return Decimal("0")

        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)

        try:
            return Decimal(str(math.sqrt(float(variance))))
        except (ValueError, OverflowError):
            return Decimal("0")

    @staticmethod
    def calculate_beta(
        asset_returns: list[Decimal],
        market_returns: list[Decimal],
    ) -> Decimal:
        """
        Calculate beta coefficient.

        Args:
            asset_returns: List of asset returns
            market_returns: List of market returns

        Returns:
            Beta coefficient
        """
        if len(asset_returns) != len(market_returns) or not asset_returns:
            return Decimal("1")

        # Calculate covariance
        asset_mean = sum(asset_returns) / len(asset_returns)
        market_mean = sum(market_returns) / len(market_returns)

        covariance = sum(
            (asset_returns[i] - asset_mean) * (market_returns[i] - market_mean) for i in range(len(asset_returns))
        ) / len(asset_returns)

        # Calculate market variance
        market_var = sum((r - market_mean) ** 2 for r in market_returns) / len(market_returns)

        if market_var == 0:
            return Decimal("0")

        return covariance / market_var


class KellyCriterion:
    """
    Position sizing using Kelly criterion.

    Calculates optimal position size based on win rate and win/loss ratio
    to maximize long-term portfolio growth.
    """

    @staticmethod
    def calculate_kelly_fraction(
        win_rate: Decimal,
        win_loss_ratio: Decimal,
    ) -> Decimal:
        """
        Calculate Kelly fraction for position sizing.

        Kelly % = (bp - q) / b
        where b = win/loss ratio, p = win rate, q = loss rate

        Args:
            win_rate: Probability of winning (0-1)
            win_loss_ratio: Ratio of win size to loss size

        Returns:
            Kelly fraction (0-1), representing optimal portfolio allocation
        """
        if win_rate <= 0 or win_rate >= 1:
            return Decimal("0")

        loss_rate = 1 - win_rate
        numerator = (win_loss_ratio * win_rate) - loss_rate
        denominator = win_loss_ratio

        if denominator == 0:
            return Decimal("0")

        kelly = numerator / denominator
        return max(Decimal("0"), min(kelly, Decimal("0.5")))  # Cap at 50%

    @staticmethod
    def calculate_fractional_kelly(
        kelly_fraction: Decimal,
        fraction: Decimal = Decimal("0.5"),
    ) -> Decimal:
        """
        Calculate fractional Kelly for conservative sizing.

        Args:
            kelly_fraction: Full Kelly fraction
            fraction: Fraction to apply (e.g., 0.5 for half-Kelly)

        Returns:
            Fractional Kelly position size
        """
        return kelly_fraction * fraction

    @staticmethod
    def calculate_position_size(
        portfolio_value: Decimal,
        kelly_fraction: Decimal,
        price: Decimal,
    ) -> Decimal:
        """
        Calculate position size in units.

        Args:
            portfolio_value: Total portfolio value
            kelly_fraction: Kelly fraction for this position
            price: Price per unit

        Returns:
            Number of units to hold
        """
        if price <= 0:
            return Decimal("0")

        notional = portfolio_value * kelly_fraction
        return notional / price


class RiskLimitManager:
    """
    Enforce risk limits on portfolio and positions.

    Tracks and enforces position limits, loss limits, and notional exposure limits.
    """

    def __init__(
        self,
        max_position_size: Decimal,
        max_notional_exposure: Decimal,
        max_loss: Decimal,
    ) -> None:
        """
        Initialize risk limit manager.

        Args:
            max_position_size: Maximum size per position
            max_notional_exposure: Maximum total notional exposure
            max_loss: Maximum loss before violation
        """
        self.max_position_size = max_position_size
        self.max_notional_exposure = max_notional_exposure
        self.max_loss = max_loss

    def check_position_limit(self, position: Position) -> None:
        """
        Check if position exceeds size limit.

        Args:
            position: Position to check

        Raises:
            RiskLimitError: If position exceeds limit
        """
        size = abs(position.get_market_value())
        if size > self.max_position_size:
            raise RiskLimitError(
                "max_position_size",
                float(size),
                float(self.max_position_size),
            )

    def check_notional_limit(self, portfolio: Portfolio) -> None:
        """
        Check if portfolio notional exposure exceeds limit.

        Args:
            portfolio: Portfolio to check

        Raises:
            RiskLimitError: If exposure exceeds limit
        """
        exposure = portfolio.get_notional_exposure()
        if exposure > self.max_notional_exposure:
            raise RiskLimitError(
                "max_notional_exposure",
                float(exposure),
                float(self.max_notional_exposure),
            )

    def check_loss_limit(self, portfolio: Portfolio) -> None:
        """
        Check if portfolio loss exceeds limit.

        Args:
            portfolio: Portfolio to check

        Raises:
            RiskLimitError: If loss exceeds limit
        """
        total_pnl = portfolio.get_total_pnl()
        if total_pnl < -self.max_loss:
            raise RiskLimitError(
                "max_loss",
                float(-total_pnl),
                float(self.max_loss),
            )
