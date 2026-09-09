"""
Tests for risk management and measurement.

Tests for Value at Risk, Expected Shortfall, Sharpe ratio, Sortino ratio,
maximum drawdown, Kelly criterion, and risk limits.
"""

from decimal import Decimal

import pytest
from _types import Portfolio, Position
from risk import (
    KellyCriterion,
    RiskCalculator,
    RiskLimitManager,
)


class TestRiskCalculator:
    """Test risk calculation methods."""

    def test_historical_var(self):
        """Test historical VaR calculation."""
        returns = [
            Decimal("0.01"),
            Decimal("0.02"),
            Decimal("-0.01"),
            Decimal("0.03"),
            Decimal("-0.02"),
            Decimal("0.01"),
            Decimal("0.04"),
            Decimal("-0.03"),
            Decimal("0.02"),
            Decimal("-0.05"),
        ]

        var = RiskCalculator.calculate_historical_var(returns, Decimal("0.95"))

        # VaR should be negative for losses
        assert var < 0
        assert var > Decimal("-0.10")

    def test_parametric_var(self):
        """Test parametric (variance-covariance) VaR."""
        mean_return = Decimal("0.01")
        volatility = Decimal("0.02")
        position_value = Decimal("100000")

        var = RiskCalculator.calculate_parametric_var(
            mean_return,
            volatility,
            Decimal("0.95"),
            position_value,
        )

        assert var < 0
        assert var > -position_value

    def test_monte_carlo_var(self):
        """Test Monte Carlo VaR."""
        mean_return = Decimal("0.01")
        volatility = Decimal("0.02")
        position_value = Decimal("100000")

        var = RiskCalculator.calculate_monte_carlo_var(
            mean_return,
            volatility,
            Decimal("0.95"),
            simulations=1000,
            periods=1,
            position_value=position_value,
        )

        assert var < 0

    def test_cvar_calculation(self):
        """Test Conditional Value at Risk (Expected Shortfall)."""
        returns = [Decimal(str(x / 100)) for x in range(-10, 11)]

        cvar = RiskCalculator.calculate_cvar(returns, Decimal("0.95"))

        # CVaR should be worse than or equal to VaR
        var = RiskCalculator.calculate_historical_var(returns, Decimal("0.95"))
        assert cvar <= var

    def test_sharpe_ratio(self):
        """Test Sharpe ratio calculation."""
        returns = [Decimal(str(x / 1000)) for x in range(10, 20)]

        sharpe = RiskCalculator.calculate_sharpe_ratio(returns, Decimal("0.02"))

        assert sharpe >= 0

    def test_sortino_ratio(self):
        """Test Sortino ratio calculation."""
        returns = [Decimal(str(x / 1000)) for x in range(10, 20)]

        sortino = RiskCalculator.calculate_sortino_ratio(returns, Decimal("0.02"))

        assert sortino >= 0

    def test_maximum_drawdown(self):
        """Test maximum drawdown calculation."""
        returns = [
            Decimal("0.10"),
            Decimal("0.05"),
            Decimal("-0.20"),
            Decimal("0.05"),
            Decimal("0.03"),
        ]

        drawdown = RiskCalculator.calculate_maximum_drawdown(returns)

        assert drawdown < 0
        assert drawdown > Decimal("-0.50")

    def test_volatility(self):
        """Test volatility calculation."""
        returns = [Decimal(str(x / 1000)) for x in range(10, 20)]

        vol = RiskCalculator.calculate_volatility(returns)

        assert vol >= 0

    def test_beta_calculation(self):
        """Test beta coefficient calculation."""
        asset_returns = [Decimal(str(x / 1000)) for x in range(10, 20)]
        market_returns = [Decimal(str(x / 1000)) for x in range(8, 18)]

        beta = RiskCalculator.calculate_beta(asset_returns, market_returns)

        # Beta should typically be around 1 for market-tracking assets
        assert beta > 0


class TestKellyCriterion:
    """Test Kelly criterion for position sizing."""

    def test_kelly_fraction_basic(self):
        """Test basic Kelly fraction calculation."""
        win_rate = Decimal("0.55")
        win_loss_ratio = Decimal("2.0")

        kelly = KellyCriterion.calculate_kelly_fraction(win_rate, win_loss_ratio)

        assert kelly > 0
        assert kelly < 1

    def test_kelly_fraction_breakeven(self):
        """Test Kelly fraction at breakeven."""
        win_rate = Decimal("0.50")
        win_loss_ratio = Decimal("1.0")

        kelly = KellyCriterion.calculate_kelly_fraction(win_rate, win_loss_ratio)

        assert kelly == 0

    def test_kelly_fraction_edge_cases(self):
        """Test Kelly fraction edge cases."""
        # Win rate of 0
        kelly = KellyCriterion.calculate_kelly_fraction(Decimal("0"), Decimal("2.0"))
        assert kelly == 0

        # Win rate of 1
        kelly = KellyCriterion.calculate_kelly_fraction(Decimal("1"), Decimal("2.0"))
        assert kelly == 0

    def test_fractional_kelly(self):
        """Test fractional Kelly sizing."""
        kelly = Decimal("0.20")
        fractional = KellyCriterion.calculate_fractional_kelly(kelly, Decimal("0.5"))

        assert fractional == Decimal("0.10")

    def test_position_sizing(self):
        """Test position size calculation."""
        portfolio_value = Decimal("100000")
        kelly_fraction = Decimal("0.10")
        price = Decimal("100")

        size = KellyCriterion.calculate_position_size(
            portfolio_value,
            kelly_fraction,
            price,
        )

        assert size == Decimal("1000")  # 10% of 100k / 100


class TestRiskLimitManager:
    """Test risk limit enforcement."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = RiskLimitManager(
            max_position_size=Decimal("50000"),
            max_notional_exposure=Decimal("500000"),
            max_loss=Decimal("10000"),
        )

    def test_position_limit_check_pass(self):
        """Test position within limit."""
        position = Position(
            symbol="AAPL",
            quantity=Decimal("100"),
            avg_price=Decimal("150"),
            current_price=Decimal("150"),
        )

        # Should not raise
        self.manager.check_position_limit(position)

    def test_position_limit_check_fail(self):
        """Test position exceeding limit."""
        position = Position(
            symbol="AAPL",
            quantity=Decimal("1000"),
            avg_price=Decimal("150"),
            current_price=Decimal("150"),
        )

        from _exceptions import RiskLimitError

        with pytest.raises(RiskLimitError):
            self.manager.check_position_limit(position)

    def test_notional_limit_check(self):
        """Test notional exposure limit."""
        portfolio = Portfolio(account_id="ACC1")

        # Add positions
        portfolio.add_position(
            Position(
                symbol="AAPL",
                quantity=Decimal("100"),
                avg_price=Decimal("150"),
                current_price=Decimal("150"),
            )
        )

        # Should pass
        self.manager.check_notional_limit(portfolio)

        # Add more positions to exceed
        portfolio.add_position(
            Position(
                symbol="MSFT",
                quantity=Decimal("1000"),
                avg_price=Decimal("300"),
                current_price=Decimal("300"),
            )
        )

        from _exceptions import RiskLimitError

        with pytest.raises(RiskLimitError):
            self.manager.check_notional_limit(portfolio)

    def test_loss_limit_check(self):
        """Test loss limit enforcement."""
        portfolio = Portfolio(account_id="ACC1")

        # Add losing position
        pos = Position(
            symbol="AAPL",
            quantity=Decimal("100"),
            avg_price=Decimal("200"),
            current_price=Decimal("150"),
        )
        portfolio.add_position(pos)

        # Should pass (loss is 5000)
        self.manager.check_loss_limit(portfolio)

        # Add another losing position
        portfolio.add_position(
            Position(
                symbol="MSFT",
                quantity=Decimal("50"),
                avg_price=Decimal("400"),
                current_price=Decimal("200"),
            )
        )

        from _exceptions import RiskLimitError

        with pytest.raises(RiskLimitError):
            self.manager.check_loss_limit(portfolio)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
