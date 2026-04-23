"""Tests for valuation module."""

from datetime import date
from decimal import Decimal

import pytest

from thomas.marketplace.real_estate._exceptions import InsufficientDataError
from thomas.marketplace.real_estate._types import Address, Comparable, Property, PropertyType, ZoningType
from thomas.marketplace.real_estate.valuation import (
    AppreciationForecasting,
    AutomatedValuationModel,
    ComparableSalesAnalysis,
    CostApproach,
    IncomeApproach,
    PricePerSquareFoot,
)


class TestComparableSalesAnalysis:
    """Test comparable sales analysis."""

    def setup_method(self):
        """Set up test fixtures."""
        self.target = Address(street="100 Main", city="City", state="ST", zip_code="12345")
        self.comp1 = Comparable(
            comparable_id="comp1",
            address=Address(street="101 Main", city="City", state="ST", zip_code="12345"),
            sale_price=Decimal("500000"),
            sale_date=date(2024, 1, 1),
            sqft=2000,
            bedrooms=3,
            bathrooms=Decimal("2"),
            age_years=10,
            condition=8,
            days_on_market=30,
        )
        self.comp2 = Comparable(
            comparable_id="comp2",
            address=Address(street="102 Main", city="City", state="ST", zip_code="12345"),
            sale_price=Decimal("520000"),
            sale_date=date(2024, 1, 15),
            sqft=2100,
            bedrooms=3,
            bathrooms=Decimal("2"),
            age_years=11,
            condition=7,
            days_on_market=25,
        )
        self.comp3 = Comparable(
            comparable_id="comp3",
            address=Address(street="103 Main", city="City", state="ST", zip_code="12345"),
            sale_price=Decimal("510000"),
            sale_date=date(2024, 2, 1),
            sqft=1950,
            bedrooms=3,
            bathrooms=Decimal("2"),
            age_years=9,
            condition=8,
            days_on_market=35,
        )

    def test_find_comparables(self):
        """Test finding comparable properties."""
        candidates = [self.comp1, self.comp2, self.comp3]
        target_prop = Property(
            property_id="target",
            address=self.target,
            property_type=PropertyType.SINGLE_FAMILY,
            zoning_type=ZoningType.RESIDENTIAL,
            bedrooms=3,
            bathrooms=Decimal("2"),
            sqft=2000,
            lot_sqft=7500,
            year_built=2014,
        )
        results = ComparableSalesAnalysis.find_comparables(target_prop, candidates)
        assert len(results) >= 2

    def test_adjust_for_sqft(self):
        """Test square footage adjustment."""
        adjusted = ComparableSalesAnalysis.adjust_for_sqft(Decimal("500000"), 2100, 2000, Decimal("250"))
        assert adjusted > Decimal("500000")

    def test_adjust_for_condition(self):
        """Test condition adjustment."""
        adjusted = ComparableSalesAnalysis.adjust_for_condition(Decimal("500000"), 8, 7)
        assert adjusted > Decimal("500000")

    def test_adjust_for_age(self):
        """Test age adjustment."""
        adjusted = ComparableSalesAnalysis.adjust_for_age(Decimal("500000"), 10, 15)
        assert adjusted > Decimal("500000")

    def test_cma_value_insufficient_data(self):
        """Test CMA raises error with insufficient comparables."""
        with pytest.raises(InsufficientDataError):
            ComparableSalesAnalysis.calculate_cma_value([self.comp1, self.comp2])

    def test_cma_value_calculation(self):
        """Test CMA value calculation."""
        comparables = [self.comp1, self.comp2, self.comp3]
        value = ComparableSalesAnalysis.calculate_cma_value(comparables)
        assert Decimal("500000") < value < Decimal("530000")


class TestIncomeApproach:
    """Test income approach valuation."""

    def test_calculate_noi(self):
        """Test NOI calculation."""
        noi = IncomeApproach.calculate_noi(Decimal("60000"), Decimal("0.05"), Decimal("15000"))
        assert noi == Decimal("42000")

    def test_calculate_cap_rate(self):
        """Test cap rate calculation."""
        cap_rate = IncomeApproach.calculate_cap_rate(Decimal("50000"), Decimal("625000"))
        assert cap_rate == Decimal("0.08")

    def test_value_from_cap_rate(self):
        """Test valuation from cap rate."""
        value = IncomeApproach.value_from_cap_rate(Decimal("50000"), Decimal("0.08"))
        assert value == Decimal("625000")

    def test_cap_rate_zero_raises_error(self):
        """Test zero cap rate raises error."""
        with pytest.raises(ValueError):
            IncomeApproach.value_from_cap_rate(Decimal("50000"), Decimal("0"))

    def test_calculate_gim(self):
        """Test GIM calculation."""
        gim = IncomeApproach.calculate_gim(Decimal("60000"), Decimal("600000"))
        assert gim == Decimal("10")


class TestCostApproach:
    """Test cost approach valuation."""

    def test_replacement_cost(self):
        """Test replacement cost calculation."""
        cost = CostApproach.calculate_replacement_cost(2000, Decimal("150"), Decimal("50000"))
        assert cost == Decimal("350000")

    def test_depreciation_calculation(self):
        """Test depreciation calculation."""
        depreciation = CostApproach.calculate_depreciation(Decimal("300000"), 10, 50)
        assert depreciation == Decimal("60000")

    def test_cost_approach_value(self):
        """Test cost approach valuation."""
        value = CostApproach.calculate_cost_approach_value(
            Decimal("100000"),
            Decimal("300000"),
            Decimal("60000"),
        )
        assert value == Decimal("340000")


class TestAutomatedValuationModel:
    """Test AVM."""

    def setup_method(self):
        """Set up test fixtures."""
        self.comparables = [
            Comparable(
                comparable_id=f"comp{i}",
                address=Address(street=f"{i} Main", city="City", state="ST", zip_code="12345"),
                sale_price=Decimal(f"{500000 + i * 5000}"),
                sale_date=date(2024, 1, 1),
                sqft=2000 + i * 50,
                bedrooms=3,
                bathrooms=Decimal("2"),
                age_years=10 + i,
                condition=7,
            )
            for i in range(6)
        ]

    def test_avm_training(self):
        """Test AVM training."""
        avm = AutomatedValuationModel()
        avm.train_from_comparables(self.comparables)
        assert avm.coefficients["sqft"] != Decimal("0")

    def test_insufficient_comparables_raises_error(self):
        """Test training with insufficient data raises error."""
        avm = AutomatedValuationModel()
        with pytest.raises(InsufficientDataError):
            avm.train_from_comparables(self.comparables[:3])

    def test_avm_prediction(self):
        """Test AVM prediction."""
        avm = AutomatedValuationModel()
        avm.train_from_comparables(self.comparables)

        target = Property(
            property_id="target",
            address=Address(street="100 Main", city="City", state="ST", zip_code="12345"),
            property_type=PropertyType.SINGLE_FAMILY,
            zoning_type=ZoningType.RESIDENTIAL,
            bedrooms=3,
            bathrooms=Decimal("2"),
            sqft=2000,
            lot_sqft=7500,
            year_built=2014,
        )
        value = avm.predict_value(target)
        assert value > Decimal("0")

    def test_avm_with_confidence(self):
        """Test AVM with confidence interval."""
        avm = AutomatedValuationModel()
        avm.train_from_comparables(self.comparables)

        target = Property(
            property_id="target",
            address=Address(street="100 Main", city="City", state="ST", zip_code="12345"),
            property_type=PropertyType.SINGLE_FAMILY,
            zoning_type=ZoningType.RESIDENTIAL,
            bedrooms=3,
            bathrooms=Decimal("2"),
            sqft=2000,
            lot_sqft=7500,
            year_built=2014,
        )
        value, confidence = avm.predict_with_confidence(target, self.comparables)
        assert value > Decimal("0")
        assert 0 <= confidence <= 1


class TestPricePerSquareFoot:
    """Test price per square foot analysis."""

    def test_calculate_ppsf(self):
        """Test PPSF calculation."""
        ppsf = PricePerSquareFoot.calculate(Decimal("500000"), 2000)
        assert ppsf == Decimal("250")

    def test_market_average(self):
        """Test market average PPSF."""
        comparables = [
            Comparable(
                comparable_id="comp1",
                address=Address(street="101 Main", city="City", state="ST", zip_code="12345"),
                sale_price=Decimal("500000"),
                sale_date=date(2024, 1, 1),
                sqft=2000,
                bedrooms=3,
                bathrooms=Decimal("2"),
                age_years=10,
                condition=8,
            ),
            Comparable(
                comparable_id="comp2",
                address=Address(street="102 Main", city="City", state="ST", zip_code="12345"),
                sale_price=Decimal("520000"),
                sale_date=date(2024, 1, 15),
                sqft=2000,
                bedrooms=3,
                bathrooms=Decimal("2"),
                age_years=10,
                condition=8,
            ),
        ]
        avg = PricePerSquareFoot.market_average(comparables)
        assert Decimal("250") < avg < Decimal("260")

    def test_estimate_value(self):
        """Test value estimation from PPSF."""
        value = PricePerSquareFoot.estimate_value(2000, Decimal("250"))
        assert value == Decimal("500000")


class TestAppreciationForecasting:
    """Test appreciation forecasting."""

    def test_linear_appreciation(self):
        """Test linear appreciation."""
        future_value = AppreciationForecasting.linear_appreciation(Decimal("500000"), Decimal("0.03"), 5)
        assert future_value == Decimal("575000")

    def test_compound_appreciation(self):
        """Test compound appreciation."""
        future_value = AppreciationForecasting.compound_appreciation(Decimal("500000"), Decimal("0.03"), 5)
        assert future_value > Decimal("575000")

    def test_historical_trend_forecast(self):
        """Test historical trend forecasting."""
        historical = [
            (date(2020, 1, 1), Decimal("400000")),
            (date(2021, 1, 1), Decimal("420000")),
            (date(2022, 1, 1), Decimal("440000")),
        ]
        forecast = AppreciationForecasting.historical_trend_forecast(historical, 2)
        assert len(forecast) == 2
        assert forecast[0][1] > Decimal("0")
