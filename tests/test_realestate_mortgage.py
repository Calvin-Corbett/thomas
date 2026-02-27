"""Tests for mortgage module."""

from datetime import date
from decimal import Decimal

import pytest

from thomas.real_estate.mortgage import (
    AffordabilityCalculator,
    APRCalculation,
    ARMSimulation,
    MortgageCalculator,
    MortgageComparison,
    PMICalculation,
    RefinanceAnalysis,
)


class TestMortgageCalculator:
    """Test mortgage payment calculations."""

    def test_monthly_payment_basic(self):
        """Test basic monthly payment calculation."""
        payment = MortgageCalculator.monthly_payment(Decimal("300000"), Decimal("0.06"), 360)
        assert Decimal("1700") < payment < Decimal("1800")

    def test_monthly_payment_zero_interest(self):
        """Test payment calculation with zero interest."""
        payment = MortgageCalculator.monthly_payment(Decimal("300000"), Decimal("0"), 360)
        assert payment == Decimal("833.33333333333333333333333333")

    def test_total_interest(self):
        """Test total interest calculation."""
        payment = Decimal("1799.10")
        total_interest = MortgageCalculator.total_interest(Decimal("300000"), payment, 360)
        assert total_interest > Decimal("300000")

    def test_amortization_schedule(self):
        """Test amortization schedule generation."""
        schedule = MortgageCalculator.amortization_schedule(Decimal("300000"), Decimal("0.06"), 360)
        assert len(schedule) == 360
        first_month = schedule[0]
        assert first_month[0] == 1
        last_month = schedule[-1]
        assert last_month[3] < Decimal("100")

    def test_remaining_balance(self):
        """Test remaining balance calculation."""
        balance = MortgageCalculator.remaining_balance(Decimal("300000"), Decimal("0.06"), 360, 180)
        assert balance > Decimal("150000")
        assert balance < Decimal("300000")


class TestAPRCalculation:
    """Test APR calculations."""

    def test_apr_from_closing_costs(self):
        """Test APR calculation with closing costs."""
        apr = APRCalculation.apr_from_closing_costs(
            Decimal("0.06"),
            Decimal("300000"),
            Decimal("6000"),
            360,
        )
        assert apr > Decimal("0.06")

    def test_yield_from_points(self):
        """Test yield impact from points."""
        yield_rate = APRCalculation.yield_from_points(Decimal("0.06"), Decimal("0.02"))
        assert yield_rate < Decimal("0.06")


class TestAffordabilityCalculator:
    """Test affordability calculations."""

    def test_max_loan_28_rule(self):
        """Test maximum loan using 28% rule."""
        max_loan = AffordabilityCalculator.max_loan_amount_28_rule(Decimal("5000"), Decimal("0.06"))
        assert max_loan > Decimal("0")

    def test_max_loan_36_rule(self):
        """Test maximum loan using 36% rule."""
        max_loan = AffordabilityCalculator.max_loan_amount_36_rule(Decimal("5000"), Decimal("500"), Decimal("0.06"))
        assert max_loan > Decimal("0")

    def test_debt_to_income_ratio(self):
        """Test DTI calculation."""
        dti = AffordabilityCalculator.debt_to_income_ratio(Decimal("1500"), Decimal("500"), Decimal("5000"))
        assert dti == Decimal("0.4")

    def test_dti_zero_income_raises_error(self):
        """Test DTI with zero income raises error."""
        with pytest.raises(ValueError):
            AffordabilityCalculator.debt_to_income_ratio(Decimal("1500"), Decimal("500"), Decimal("0"))


class TestMortgageComparison:
    """Test mortgage comparison."""

    def test_compare_terms(self):
        """Test comparing different terms."""
        results = MortgageComparison.compare_terms(
            Decimal("300000"),
            Decimal("0.06"),
            [180, 240, 360],
        )
        assert len(results) == 3
        assert results[0][1] > results[2][1]

    def test_compare_rates(self):
        """Test comparing different rates."""
        results = MortgageComparison.compare_rates(
            Decimal("300000"),
            360,
            [Decimal("0.05"), Decimal("0.06"), Decimal("0.07")],
        )
        assert len(results) == 3
        assert results[0][1] < results[2][1]


class TestRefinanceAnalysis:
    """Test refinance analysis."""

    def test_break_even_calculation(self):
        """Test break-even calculation."""
        break_even = RefinanceAnalysis.refinance_break_even(
            Decimal("280000"),
            Decimal("0.06"),
            Decimal("0.04"),
            300,
            360,
            Decimal("6000"),
        )
        assert break_even > 0

    def test_should_refinance(self):
        """Test refinance recommendation."""
        should_refi = RefinanceAnalysis.should_refinance(
            Decimal("280000"),
            Decimal("0.06"),
            Decimal("0.04"),
            300,
            360,
            Decimal("6000"),
        )
        assert should_refi is True

    def test_should_not_refinance(self):
        """Test when refinance not recommended."""
        should_refi = RefinanceAnalysis.should_refinance(
            Decimal("280000"),
            Decimal("0.06"),
            Decimal("0.055"),
            300,
            360,
            Decimal("6000"),
        )
        assert should_refi is False


class TestARMSimulation:
    """Test ARM simulation."""

    def test_arm_adjustments(self):
        """Test ARM rate adjustments."""
        adjustments = ARMSimulation.simulate_arm_adjustments(
            Decimal("300000"),
            Decimal("0.04"),
            180,
            [date(2027, 1, 1), date(2029, 1, 1)],
            [Decimal("0.05"), Decimal("0.06")],
        )
        assert len(adjustments) == 2

    def test_arm_with_rate_cap(self):
        """Test ARM with rate cap."""
        adjustments = ARMSimulation.simulate_arm_adjustments(
            Decimal("300000"),
            Decimal("0.04"),
            180,
            [date(2027, 1, 1)],
            [Decimal("0.07")],
            rate_cap=Decimal("0.06"),
        )
        assert adjustments[0][1] == Decimal("0.06")


class TestPMICalculation:
    """Test PMI calculations."""

    def test_pmi_rate_80_ltv(self):
        """Test PMI rate at 80% LTV."""
        rate = PMICalculation.calculate_pmi_rate(Decimal("0.80"))
        assert rate == Decimal("0")

    def test_pmi_rate_85_ltv(self):
        """Test PMI rate at 85% LTV."""
        rate = PMICalculation.calculate_pmi_rate(Decimal("0.85"))
        assert rate > Decimal("0")

    def test_pmi_rate_95_ltv(self):
        """Test PMI rate at 95% LTV."""
        rate = PMICalculation.calculate_pmi_rate(Decimal("0.95"))
        assert rate > Decimal("0.01")

    def test_monthly_pmi(self):
        """Test monthly PMI calculation."""
        pmi = PMICalculation.calculate_monthly_pmi(Decimal("300000"), Decimal("0.0085"))
        assert pmi > Decimal("0")

    def test_pmi_payoff_date(self):
        """Test estimating PMI payoff date."""
        payoff_date = PMICalculation.pmi_payoff_date(
            Decimal("240000"),
            Decimal("60000"),
            Decimal("0.06"),
            360,
        )
        assert payoff_date > date.today()


class TestIntegration:
    """Integration tests."""

    def test_full_mortgage_scenario(self):
        """Test complete mortgage scenario."""
        principal = Decimal("300000")
        rate = Decimal("0.065")
        term = 360

        payment = MortgageCalculator.monthly_payment(principal, rate, term)
        assert payment > Decimal("0")

        interest = MortgageCalculator.total_interest(principal, payment, term)
        assert interest > Decimal("0")

        schedule = MortgageCalculator.amortization_schedule(principal, rate, term)
        assert len(schedule) == term

        dti = AffordabilityCalculator.debt_to_income_ratio(payment, Decimal("500"), Decimal("5000"))
        assert dti < Decimal("0.5")
