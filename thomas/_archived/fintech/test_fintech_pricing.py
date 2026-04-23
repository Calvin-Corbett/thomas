"""
Tests for financial instrument pricing.

Tests for Black-Scholes option pricing, Greeks, bond pricing,
implied volatility, and time value calculations.
"""

from decimal import Decimal

import pytest
from pricing import (
    BlackScholesCalculator,
    BondCalculator,
    ImpliedVolatilityCalculator,
    OptionType,
    TimeValueCalculator,
)


class TestBlackScholesCalculator:
    """Test Black-Scholes option pricing."""

    def test_call_option_pricing(self):
        """Test call option pricing."""
        price = BlackScholesCalculator.calculate_option_price(
            spot_price=Decimal("100"),
            strike_price=Decimal("100"),
            time_to_expiry=Decimal("1"),
            volatility=Decimal("0.2"),
            risk_free_rate=Decimal("0.05"),
            option_type=OptionType.CALL,
        )

        # At-the-money call should have positive value
        assert price > 0
        # Should be less than intrinsic value for long time
        assert price < Decimal("10")

    def test_put_option_pricing(self):
        """Test put option pricing."""
        price = BlackScholesCalculator.calculate_option_price(
            spot_price=Decimal("100"),
            strike_price=Decimal("100"),
            time_to_expiry=Decimal("1"),
            volatility=Decimal("0.2"),
            risk_free_rate=Decimal("0.05"),
            option_type=OptionType.PUT,
        )

        assert price > 0

    def test_in_the_money_call(self):
        """Test in-the-money call option."""
        itm_price = BlackScholesCalculator.calculate_option_price(
            spot_price=Decimal("110"),
            strike_price=Decimal("100"),
            time_to_expiry=Decimal("1"),
            volatility=Decimal("0.2"),
            risk_free_rate=Decimal("0.05"),
            option_type=OptionType.CALL,
        )

        otm_price = BlackScholesCalculator.calculate_option_price(
            spot_price=Decimal("90"),
            strike_price=Decimal("100"),
            time_to_expiry=Decimal("1"),
            volatility=Decimal("0.2"),
            risk_free_rate=Decimal("0.05"),
            option_type=OptionType.CALL,
        )

        # ITM should be worth more
        assert itm_price > otm_price

    def test_greeks_calculation(self):
        """Test Greeks calculation."""
        greeks = BlackScholesCalculator.calculate_greeks(
            spot_price=Decimal("100"),
            strike_price=Decimal("100"),
            time_to_expiry=Decimal("1"),
            volatility=Decimal("0.2"),
            risk_free_rate=Decimal("0.05"),
            option_type=OptionType.CALL,
        )

        # Delta for ATM call should be around 0.5
        assert Decimal("0.4") < greeks.delta < Decimal("0.6")
        # Gamma should be positive
        assert greeks.gamma > 0
        # Vega should be positive
        assert greeks.vega > 0
        # Theta should be small for ATM
        assert abs(greeks.theta) < Decimal("0.01")

    def test_delta_range(self):
        """Test delta ranges for options."""
        # ITM call delta should approach 1
        itm_delta = BlackScholesCalculator.calculate_greeks(
            spot_price=Decimal("150"),
            strike_price=Decimal("100"),
            time_to_expiry=Decimal("1"),
            volatility=Decimal("0.2"),
            risk_free_rate=Decimal("0.05"),
            option_type=OptionType.CALL,
        ).delta

        # OTM call delta should approach 0
        otm_delta = BlackScholesCalculator.calculate_greeks(
            spot_price=Decimal("50"),
            strike_price=Decimal("100"),
            time_to_expiry=Decimal("1"),
            volatility=Decimal("0.2"),
            risk_free_rate=Decimal("0.05"),
            option_type=OptionType.CALL,
        ).delta

        assert itm_delta > otm_delta
        assert itm_delta > Decimal("0.7")
        assert otm_delta < Decimal("0.3")


class TestImpliedVolatilityCalculator:
    """Test implied volatility calculation."""

    def test_implied_volatility_basic(self):
        """Test basic implied volatility calculation."""
        # First, calculate a price
        market_price = BlackScholesCalculator.calculate_option_price(
            spot_price=Decimal("100"),
            strike_price=Decimal("100"),
            time_to_expiry=Decimal("1"),
            volatility=Decimal("0.2"),
            risk_free_rate=Decimal("0.05"),
            option_type=OptionType.CALL,
        )

        # Now find implied vol
        implied_vol = ImpliedVolatilityCalculator.calculate_implied_volatility(
            option_price=market_price,
            spot_price=Decimal("100"),
            strike_price=Decimal("100"),
            time_to_expiry=Decimal("1"),
            risk_free_rate=Decimal("0.05"),
            option_type=OptionType.CALL,
        )

        # Should recover original volatility
        assert implied_vol is not None
        assert abs(implied_vol - Decimal("0.2")) < Decimal("0.01")

    def test_implied_volatility_convergence(self):
        """Test that implied volatility converges."""
        market_price = Decimal("5.0")

        implied_vol = ImpliedVolatilityCalculator.calculate_implied_volatility(
            option_price=market_price,
            spot_price=Decimal("100"),
            strike_price=Decimal("100"),
            time_to_expiry=Decimal("1"),
            risk_free_rate=Decimal("0.05"),
        )

        assert implied_vol is not None
        assert implied_vol > 0


class TestBondCalculator:
    """Test bond pricing and yield calculations."""

    def test_bond_present_value(self):
        """Test bond price calculation."""
        price = BondCalculator.calculate_present_value(
            face_value=Decimal("1000"),
            coupon_rate=Decimal("0.05"),
            yield_to_maturity=Decimal("0.05"),
            years_to_maturity=Decimal("10"),
        )

        # At par yield, price should equal face value
        assert abs(price - Decimal("1000")) < Decimal("1")

    def test_bond_premium_discount(self):
        """Test premium and discount bonds."""
        # Premium bond (coupon > ytm)
        premium = BondCalculator.calculate_present_value(
            face_value=Decimal("1000"),
            coupon_rate=Decimal("0.06"),
            yield_to_maturity=Decimal("0.04"),
            years_to_maturity=Decimal("10"),
        )

        # Discount bond (coupon < ytm)
        discount = BondCalculator.calculate_present_value(
            face_value=Decimal("1000"),
            coupon_rate=Decimal("0.04"),
            yield_to_maturity=Decimal("0.06"),
            years_to_maturity=Decimal("10"),
        )

        assert premium > Decimal("1000")
        assert discount < Decimal("1000")

    def test_bond_yield_to_maturity(self):
        """Test YTM calculation."""
        bond_price = Decimal("950")

        ytm = BondCalculator.calculate_yield_to_maturity(
            bond_price=bond_price,
            face_value=Decimal("1000"),
            coupon_rate=Decimal("0.05"),
            years_to_maturity=Decimal("10"),
        )

        assert ytm is not None
        # YTM should be higher than coupon for discount bond
        assert ytm > Decimal("0.05")

    def test_bond_duration(self):
        """Test bond duration calculation."""
        duration = BondCalculator.calculate_duration(
            face_value=Decimal("1000"),
            coupon_rate=Decimal("0.05"),
            yield_to_maturity=Decimal("0.05"),
            years_to_maturity=Decimal("10"),
        )

        # Duration should be less than maturity
        assert duration > 0
        assert duration < Decimal("10")

    def test_bond_convexity(self):
        """Test bond convexity calculation."""
        convexity = BondCalculator.calculate_convexity(
            face_value=Decimal("1000"),
            coupon_rate=Decimal("0.05"),
            yield_to_maturity=Decimal("0.05"),
            years_to_maturity=Decimal("10"),
        )

        # Convexity should be positive
        assert convexity > 0


class TestTimeValueCalculator:
    """Test present/future value calculations."""

    def test_present_value(self):
        """Test present value calculation."""
        pv = TimeValueCalculator.calculate_present_value(
            future_value=Decimal("110"),
            discount_rate=Decimal("0.10"),
            periods=Decimal("1"),
        )

        assert pv == Decimal("100")

    def test_future_value(self):
        """Test future value calculation."""
        fv = TimeValueCalculator.calculate_future_value(
            present_value=Decimal("100"),
            rate=Decimal("0.10"),
            periods=Decimal("1"),
        )

        assert fv == Decimal("110")

    def test_amortization_schedule(self):
        """Test amortization schedule generation."""
        schedule = TimeValueCalculator.calculate_amortization_schedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.05"),
            years=Decimal("5"),
            payments_per_year=12,
        )

        # Should have 60 payments
        assert len(schedule) == 60

        # Payments should be constant
        payment = schedule[0]["payment"]
        for payment_item in schedule:
            assert abs(payment_item["payment"] - payment) < Decimal("0.01")

        # Final balance should be near zero
        assert abs(schedule[-1]["balance"]) < Decimal("1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
