"""Tests for farm economics module."""

from decimal import Decimal

import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)

from thomas.agriculture.economics import (
    BreakEvenAnalysis,
    CropInsuranceAnalysis,
    EnterpriseBudget,
    FarmFinancialRatios,
    FuturesHedging,
    LandValuation,
    MachineryCosting,
    MarketPriceTracking,
)


class TestEnterpriseBudget:
    """Test enterprise budget calculations."""

    def setup_method(self) -> None:
        """Setup budget calculator."""
        self.budget = EnterpriseBudget()

    def test_calculate_crop_budget(self) -> None:
        """Test crop enterprise budget."""
        budget = self.budget.calculate_crop_budget(
            crop_type="Corn",
            acres=100,
            yield_bu_acre=150,
            price_per_bu=4.00,
            seed_cost_per_acre=30,
            fertilizer_cost_per_acre=50,
            pesticide_cost_per_acre=15,
            fuel_cost_per_acre=15,
            labor_cost_per_acre=20,
            equipment_cost_per_acre=30,
            land_rent_per_acre=150,
        )

        # Gross revenue: 100 Ã— 150 Ã— $4 = $60,000
        assert budget["gross_revenue"] == Decimal("60000")

        # Variable cost: 100 Ã— (30+50+15+15+20) = $13,000
        assert budget["variable_cost"] == Decimal("13000")

        # Fixed cost: 100 Ã— (30+150) = $18,000
        assert budget["fixed_cost"] == Decimal("18000")

        # Net return should be positive
        assert budget["net_return"] > 0

    def test_calculate_livestock_budget(self) -> None:
        """Test livestock enterprise budget."""
        budget = self.budget.calculate_livestock_budget(
            livestock_type="Cattle",
            animal_units=10,
            selling_price_per_lb=1.20,
            target_weight_gain_lbs=400,
            feed_cost_per_day_per_au=10,
            days_on_feed=200,
            labor_cost_per_au=50,
            facilities_cost_per_au=100,
            health_medicine_cost_per_au=30,
        )

        # Revenue: 10 AU Ã— 400 lbs Ã— $1.20 = $4,800
        assert budget["gross_revenue"] == Decimal("4800")

        # Feed cost: 10 AU Ã— $10/day Ã— 200 days = $20,000
        assert budget["feed_cost"] == Decimal("20000")

        # Should have negative net return (feed expensive)
        assert budget["net_return"] < 0


class TestBreakEvenAnalysis:
    """Test break-even analysis."""

    def test_break_even_yield(self) -> None:
        """Test break-even yield calculation."""
        break_even = BreakEvenAnalysis.break_even_yield(
            total_cost_per_acre=150,
            price_per_bu=4.00,
        )

        # $150 / $4 = 37.5 bu/acre
        assert abs(break_even - 37.5) < 0.01

    def test_break_even_price(self) -> None:
        """Test break-even price calculation."""
        break_even = BreakEvenAnalysis.break_even_price(
            total_cost_per_acre=150,
            yield_bu_acre=50,
        )

        # $150 / 50 = $3.00/bu
        assert abs(break_even - 3.00) < 0.01

    def test_break_even_zero_price_error(self) -> None:
        """Test error with zero price."""
        with pytest.raises(Exception):
            BreakEvenAnalysis.break_even_yield(
                total_cost_per_acre=150,
                price_per_bu=0.0,
            )

    def test_break_even_zero_yield_error(self) -> None:
        """Test error with zero yield."""
        with pytest.raises(Exception):
            BreakEvenAnalysis.break_even_price(
                total_cost_per_acre=150,
                yield_bu_acre=0.0,
            )

    def test_sensitivity_analysis(self) -> None:
        """Test sensitivity analysis."""
        analysis = BreakEvenAnalysis.sensitivity_analysis(
            base_price=4.00,
            base_yield=150,
            total_cost=300,
            price_range_pct=20,
            yield_range_pct=20,
        )

        # Should have multiple scenarios
        assert len(analysis) > 1


class TestCropInsuranceAnalysis:
    """Test crop insurance analysis."""

    def setup_method(self) -> None:
        """Setup insurance analysis."""
        self.insurance = CropInsuranceAnalysis()

    def test_calculate_aph_yield(self) -> None:
        """Test APH yield calculation."""
        historical_yields = [100, 120, 140, 150, 160]

        aph = self.insurance.calculate_aph_yield(
            historical_yields=historical_yields,
            exclude_lowest=True,
        )

        # (120 + 140 + 150 + 160) / 4 = 142.5
        assert abs(aph - 142.5) < 0.1

    def test_aph_without_exclude_lowest(self) -> None:
        """Test APH without excluding lowest."""
        historical_yields = [100, 120, 140, 150, 160]

        aph = self.insurance.calculate_aph_yield(
            historical_yields=historical_yields,
            exclude_lowest=False,
        )

        # (100 + 120 + 140 + 150 + 160) / 5 = 134
        assert abs(aph - 134.0) < 0.1

    def test_calculate_insurance_premium(self) -> None:
        """Test insurance premium calculation."""
        premium = CropInsuranceAnalysis.calculate_insurance_premium(
            aph_yield=150,
            coverage_level_pct=75,
            base_rate_pct=0.04,
        )

        # 150 Ã— 75% Ã— 4% = 4.5
        assert abs(premium - 4.5) < 0.1

    def test_calculate_indemnity(self) -> None:
        """Test indemnity payment calculation."""
        indemnity = CropInsuranceAnalysis.calculate_indemnity(
            aph_yield=150,
            coverage_level_pct=75,
            actual_yield=100,
            price_per_bu=4.00,
        )

        # Covered yield: 150 Ã— 75% = 112.5
        # Loss: 112.5 - 100 = 12.5
        # Indemnity: 12.5 Ã— $4 = $50
        assert abs(indemnity - 50.0) < 0.1

    def test_no_indemnity_when_above_covered(self) -> None:
        """Test no indemnity when yield above covered."""
        indemnity = CropInsuranceAnalysis.calculate_indemnity(
            aph_yield=150,
            coverage_level_pct=75,
            actual_yield=130,
            price_per_bu=4.00,
        )

        # Actual (130) > Covered (112.5), no payment
        assert indemnity == 0


class TestMarketPriceTracking:
    """Test market price tracking."""

    def setup_method(self) -> None:
        """Setup price tracker."""
        self.tracker = MarketPriceTracking()

    def test_record_price(self) -> None:
        """Test recording prices."""
        self.tracker.record_price("Corn", "2024-01-01", 4.00)
        self.tracker.record_price("Corn", "2024-01-08", 4.10)
        self.tracker.record_price("Corn", "2024-01-15", 3.95)

        history = self.tracker.price_history["Corn"]
        assert len(history) == 3

    def test_calculate_average_price(self) -> None:
        """Test average price calculation."""
        self.tracker.record_price("Corn", "2024-01-01", 4.00)
        self.tracker.record_price("Corn", "2024-01-08", 4.10)
        self.tracker.record_price("Corn", "2024-01-15", 3.90)

        avg = self.tracker.calculate_average_price("Corn")

        # (4.00 + 4.10 + 3.90) / 3 = 4.00
        assert abs(avg - 4.00) < 0.01

    def test_calculate_price_volatility(self) -> None:
        """Test price volatility calculation."""
        self.tracker.record_price("Corn", "2024-01-01", 4.00)
        self.tracker.record_price("Corn", "2024-01-08", 5.00)
        self.tracker.record_price("Corn", "2024-01-15", 3.00)

        volatility = self.tracker.calculate_price_volatility("Corn")

        # Should be positive (prices vary)
        assert volatility > 0


class TestFuturesHedging:
    """Test futures hedging simulation."""

    def test_hedge_price_calculation(self) -> None:
        """Test hedged price calculation."""
        hedge = FuturesHedging.hedge_price(
            bushels_produced=1000,
            futures_contract_price=4.00,
            basis_points=-20,
        )

        # Basis: -20 cents = -$0.20
        # Locked-in price: $4.00 - $0.20 = $3.80
        assert abs(hedge["locked_in_price"] - 3.80) < 0.01

        # Revenue: 1000 Ã— $3.80 = $3,800
        assert abs(hedge["hedged_revenue"] - 3800.0) < 1

    def test_hedge_reduces_risk(self) -> None:
        """Test hedging reduces price risk."""
        # Spot price range $3-5
        unhedged_low = 1000 * 3.00
        unhedged_high = 1000 * 5.00

        hedge = FuturesHedging.hedge_price(
            bushels_produced=1000,
            futures_contract_price=4.00,
            basis_points=-20,
        )

        hedged_revenue = hedge["hedged_revenue"]

        # Hedged revenue should be between extremes
        assert unhedged_low < hedged_revenue < unhedged_high


class TestLandValuation:
    """Test land valuation."""

    def test_calculate_capitalized_land_value(self) -> None:
        """Test capitalized land value calculation."""
        land_value = LandValuation.calculate_capitalized_land_value(
            annual_net_return_per_acre=100,
            capitalization_rate=0.05,
        )

        # $100 / 0.05 = $2,000/acre
        assert abs(land_value - 2000) < 1

    def test_land_value_varies_by_return(self) -> None:
        """Test land value increases with return."""
        value_100 = LandValuation.calculate_capitalized_land_value(
            annual_net_return_per_acre=100,
            capitalization_rate=0.05,
        )

        value_200 = LandValuation.calculate_capitalized_land_value(
            annual_net_return_per_acre=200,
            capitalization_rate=0.05,
        )

        assert value_200 > value_100

    def test_calculate_fair_land_rent(self) -> None:
        """Test fair land rent calculation."""
        rent = LandValuation.calculate_fair_land_rent(
            annual_net_return_per_acre=100,
            land_value_per_acre=2000,
            target_return_pct=5.0,
        )

        # Should be positive and reasonable
        assert 0 < rent < 100


class TestMachineryCosting:
    """Test machinery cost calculations."""

    def test_calculate_annual_machinery_cost(self) -> None:
        """Test annual machinery cost."""
        costs = MachineryCosting.calculate_annual_machinery_cost(
            purchase_price=100000,
            useful_life_years=10,
            salvage_value_pct=10,
            hours_per_year=200,
            fuel_gph=5,
            fuel_price_per_gal=3.00,
        )

        # Depreciation: ($100,000 - $10,000) / 10 = $9,000
        assert 8900 < costs["depreciation"] < 9100

        # Total cost should include all components
        assert costs["total_annual_cost"] > costs["depreciation"]

        # Cost per hour should be positive
        assert costs["cost_per_hour"] > 0

    def test_machinery_cost_per_hour(self) -> None:
        """Test cost per hour increases with higher costs."""
        costs_low_hours = MachineryCosting.calculate_annual_machinery_cost(
            purchase_price=50000,
            useful_life_years=10,
            hours_per_year=100,
        )

        costs_high_hours = MachineryCosting.calculate_annual_machinery_cost(
            purchase_price=50000,
            useful_life_years=10,
            hours_per_year=200,
        )

        # Higher hours spread fixed costs, lower per-hour cost
        assert costs_high_hours["cost_per_hour"] < costs_low_hours["cost_per_hour"]


class TestFarmFinancialRatios:
    """Test farm financial ratios."""

    def test_calculate_profit_margin(self) -> None:
        """Test profit margin calculation."""
        margin = FarmFinancialRatios.calculate_profit_margin(
            net_return=10000,
            gross_revenue=100000,
        )

        # $10,000 / $100,000 = 10%
        assert abs(margin - 10.0) < 0.1

    def test_calculate_operating_ratio(self) -> None:
        """Test operating ratio calculation."""
        ratio = FarmFinancialRatios.calculate_operating_ratio(
            operating_cost=70000,
            gross_revenue=100000,
        )

        # $70,000 / $100,000 = 0.7
        assert abs(ratio - 0.7) < 0.01

    def test_operating_ratio_good_vs_bad(self) -> None:
        """Test good vs bad operating ratio."""
        good_ratio = FarmFinancialRatios.calculate_operating_ratio(
            operating_cost=60000,
            gross_revenue=100000,
        )

        bad_ratio = FarmFinancialRatios.calculate_operating_ratio(
            operating_cost=90000,
            gross_revenue=100000,
        )

        # Good ratio should be lower
        assert good_ratio < bad_ratio

    def test_calculate_roa(self) -> None:
        """Test Return on Assets calculation."""
        roa = FarmFinancialRatios.calculate_roa(
            net_return=50000,
            total_assets=1000000,
        )

        # $50,000 / $1,000,000 = 5%
        assert abs(roa - 5.0) < 0.1

    def test_calculate_debt_to_equity(self) -> None:
        """Test debt-to-equity ratio."""
        ratio = FarmFinancialRatios.calculate_debt_to_equity(
            total_debt=300000,
            total_equity=700000,
        )

        # $300,000 / $700,000 = 0.43
        assert abs(ratio - 0.43) < 0.01

    def test_debt_to_equity_leverage_comparison(self) -> None:
        """Test debt-to-equity shows leverage difference."""
        conservative = FarmFinancialRatios.calculate_debt_to_equity(
            total_debt=100000,
            total_equity=900000,
        )

        leveraged = FarmFinancialRatios.calculate_debt_to_equity(
            total_debt=500000,
            total_equity=500000,
        )

        # Leveraged operation has higher ratio
        assert leveraged > conservative
