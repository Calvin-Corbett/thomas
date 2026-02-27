"""Tests for investment analysis module."""

from decimal import Decimal

import pytest

from thomas.real_estate.investment import (
    AcquisitionAnalysis,
    CapRateAnalysis,
    CashFlowProjection,
    ExchangeTracking,
    LeverageAnalysis,
    PortfolioAnalysis,
    ReturnCalculation,
)


class TestCashFlowProjection:
    """Test cash flow projections."""

    def test_annual_cash_flow(self):
        """Test annual cash flow calculation."""
        cash_flow = CashFlowProjection.calculate_annual_cash_flow(
            Decimal("60000"),
            Decimal("0.05"),
            Decimal("15000"),
            Decimal("24000"),
        )
        assert cash_flow == Decimal("36000")

    def test_cash_flow_with_vacancy(self):
        """Test cash flow with vacancy impact."""
        cash_flow = CashFlowProjection.calculate_annual_cash_flow(
            Decimal("60000"),
            Decimal("0.10"),
            Decimal("15000"),
            Decimal("24000"),
        )
        assert cash_flow == Decimal("33000")

    def test_cash_flow_projection(self):
        """Test multi-year cash flow projection."""
        projections = CashFlowProjection.project_cash_flows(
            Decimal("60000"),
            Decimal("0.02"),
            Decimal("0.03"),
            Decimal("24000"),
            5,
        )
        assert len(projections) == 5

    def test_cumulative_cash_flow(self):
        """Test cumulative cash flow."""
        cash_flows = [
            Decimal("12000"),
            Decimal("12000"),
            Decimal("12000"),
            Decimal("12000"),
            Decimal("12000"),
        ]
        cumulative = CashFlowProjection.calculate_cumulative_cash_flow(cash_flows)
        assert cumulative[-1] == Decimal("60000")


class TestCapRateAnalysis:
    """Test cap rate analysis."""

    def test_cap_rate_calculation(self):
        """Test cap rate calculation."""
        cap_rate = CapRateAnalysis.calculate_cap_rate(Decimal("50000"), Decimal("625000"))
        assert cap_rate == Decimal("0.08")

    def test_cap_rate_comparison(self):
        """Test comparing cap rates across properties."""
        properties = [
            ("prop1", Decimal("50000"), Decimal("625000")),
            ("prop2", Decimal("45000"), Decimal("500000")),
            ("prop3", Decimal("55000"), Decimal("700000")),
        ]
        results = CapRateAnalysis.compare_cap_rates(properties)
        assert len(results) == 3
        assert results[0][1] >= results[1][1]


class TestReturnCalculation:
    """Test return calculations."""

    def test_cash_on_cash_return(self):
        """Test cash-on-cash return."""
        returns = ReturnCalculation.cash_on_cash_return(Decimal("12000"), Decimal("100000"))
        assert returns == Decimal("0.12")

    def test_net_present_value(self):
        """Test NPV calculation."""
        cash_flows = [
            Decimal("-100000"),
            Decimal("25000"),
            Decimal("25000"),
            Decimal("25000"),
            Decimal("25000"),
        ]
        npv = ReturnCalculation.net_present_value(cash_flows, Decimal("0.10"))
        assert npv > Decimal("0")

    def test_irr_calculation(self):
        """Test IRR calculation."""
        irr = ReturnCalculation.internal_rate_of_return(
            Decimal("100000"),
            [Decimal("25000"), Decimal("25000"), Decimal("25000")],
            Decimal("30000"),
        )
        assert irr is not None
        assert irr > Decimal("0")


class TestLeverageAnalysis:
    """Test leverage and financing analysis."""

    def test_dscr_calculation(self):
        """Test DSCR calculation."""
        dscr = LeverageAnalysis.debt_service_coverage_ratio(Decimal("50000"), Decimal("30000"))
        assert dscr == pytest.approx(Decimal("1.667"), abs=Decimal("0.001"))

    def test_loan_to_value(self):
        """Test LTV calculation."""
        ltv = LeverageAnalysis.loan_to_value_ratio(Decimal("300000"), Decimal("500000"))
        assert ltv == Decimal("0.6")

    def test_equity_ratio(self):
        """Test equity ratio calculation."""
        equity = LeverageAnalysis.equity_ratio(Decimal("300000"), Decimal("500000"))
        assert equity == Decimal("0.4")

    def test_break_even_occupancy(self):
        """Test break-even occupancy rate."""
        occupancy = LeverageAnalysis.break_even_occupancy_rate(
            Decimal("1500"),
            10,
            Decimal("5000"),
            Decimal("2000"),
        )
        assert occupancy > Decimal("0")
        assert occupancy < Decimal("1")

    def test_grm_calculation(self):
        """Test GRM calculation."""
        grm = LeverageAnalysis.gross_rent_multiplier(Decimal("600000"), Decimal("60000"))
        assert grm == Decimal("10")


class TestAcquisitionAnalysis:
    """Test acquisition analysis."""

    def test_maximum_offer_price(self):
        """Test maximum offer price calculation."""
        max_price = AcquisitionAnalysis.maximum_offer_price(Decimal("0.08"), Decimal("50000"))
        assert max_price == Decimal("625000")

    def test_closing_costs_estimate(self):
        """Test closing costs estimation."""
        costs = AcquisitionAnalysis.estimate_closing_costs(Decimal("500000"), Decimal("0.02"))
        assert costs == Decimal("10000")

    def test_total_capital_required(self):
        """Test total capital required."""
        capital = AcquisitionAnalysis.total_capital_required(
            Decimal("500000"),
            Decimal("0.20"),
            Decimal("10000"),
            Decimal("5000"),
        )
        assert capital == Decimal("115000")


class TestExchangeTracking:
    """Test 1031 exchange tracking."""

    def setup_method(self):
        """Set up test fixtures."""
        self.tracker = ExchangeTracking()

    def test_create_exchange(self):
        """Test creating exchange record."""
        self.tracker.create_exchange(
            "exchange001",
            "prop001",
            Decimal("500000"),
        )
        assert "exchange001" in self.tracker._exchanges

    def test_add_replacement_property(self):
        """Test adding replacement property."""
        self.tracker.create_exchange(
            "exchange001",
            "prop001",
            Decimal("500000"),
        )
        self.tracker.add_replacement_property("exchange001", "prop002", Decimal("550000"))
        exchange = self.tracker._exchanges["exchange001"]
        assert len(exchange["replacement_properties"]) == 1

    def test_verify_exchange_rules(self):
        """Test exchange verification."""
        self.tracker.create_exchange(
            "exchange001",
            "prop001",
            Decimal("500000"),
        )
        self.tracker.add_replacement_property("exchange001", "prop002", Decimal("550000"))
        valid = self.tracker.verify_exchange_rules("exchange001")
        assert valid is True

    def test_exchange_rules_fail_undersupply(self):
        """Test exchange verification fails with undersupply."""
        self.tracker.create_exchange(
            "exchange001",
            "prop001",
            Decimal("500000"),
        )
        self.tracker.add_replacement_property("exchange001", "prop002", Decimal("400000"))
        valid = self.tracker.verify_exchange_rules("exchange001")
        assert valid is False


class TestPortfolioAnalysis:
    """Test portfolio analysis."""

    def setup_method(self):
        """Set up test fixtures."""
        self.properties = [
            ("prop1", Decimal("500000")),
            ("prop2", Decimal("400000")),
            ("prop3", Decimal("600000")),
        ]

    def test_portfolio_total_value(self):
        """Test total portfolio value."""
        total = PortfolioAnalysis.portfolio_total_value(self.properties)
        assert total == Decimal("1500000")

    def test_portfolio_average_value(self):
        """Test average property value."""
        avg = PortfolioAnalysis.portfolio_average_value(self.properties)
        assert avg == Decimal("500000")

    def test_portfolio_concentration(self):
        """Test portfolio concentration."""
        concentration = PortfolioAnalysis.portfolio_concentration(self.properties)
        assert len(concentration) == 3
        total_pct = sum(concentration.values())
        assert total_pct == pytest.approx(Decimal("1"), abs=Decimal("0.01"))

    def test_diversification_score_concentrated(self):
        """Test diversification score for concentrated portfolio."""
        concentrated = [
            ("prop1", Decimal("900000")),
            ("prop2", Decimal("100000")),
        ]
        concentration = PortfolioAnalysis.portfolio_concentration(concentrated)
        score = PortfolioAnalysis.portfolio_diversification_score(concentration)
        assert score < 0.5

    def test_diversification_score_balanced(self):
        """Test diversification score for balanced portfolio."""
        concentration = PortfolioAnalysis.portfolio_concentration(self.properties)
        score = PortfolioAnalysis.portfolio_diversification_score(concentration)
        assert score > 0.5


class TestIntegration:
    """Integration tests."""

    def test_full_investment_analysis(self):
        """Test complete investment analysis."""
        annual_income = Decimal("60000")
        annual_expenses = Decimal("15000")
        noi = annual_income - annual_expenses

        purchase_price = Decimal("625000")
        cap_rate = CapRateAnalysis.calculate_cap_rate(noi, purchase_price)
        assert cap_rate == pytest.approx(Decimal("0.072"), abs=Decimal("0.001"))

        down_payment = Decimal("125000")
        loan_amount = purchase_price - down_payment
        dscr = LeverageAnalysis.debt_service_coverage_ratio(noi, Decimal("30000"))
        assert dscr > Decimal("1.5")

        max_loan = LeverageAnalysis.max_loan_amount_36_rule(Decimal("5000"), Decimal("1000"), Decimal("0.06"))
        assert max_loan > Decimal("0")
