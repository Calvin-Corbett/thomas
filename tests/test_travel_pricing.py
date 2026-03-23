"""Tests for dynamic pricing module."""

from datetime import date
from decimal import Decimal

import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)

from thomas.marketplace.travel._exceptions import CurrencyConversionError
from thomas.marketplace.travel._types import Currency, FareClass
from thomas.marketplace.travel.pricing import (
    BundleDiscountCalculator,
    CurrencyConverter,
    DemandForecast,
    FareRuleEngine,
    PriceComparisonEngine,
    PriceElasticityModel,
    YieldManagementSystem,
)


@pytest.fixture
def demand_forecast():
    """Create demand forecaster."""
    return DemandForecast()


@pytest.fixture
def yield_system():
    """Create yield management system."""
    return YieldManagementSystem()


@pytest.fixture
def currency_converter():
    """Create currency converter."""
    return CurrencyConverter()


@pytest.fixture
def comparison_engine():
    """Create price comparison engine."""
    return PriceComparisonEngine()


@pytest.fixture
def bundle_calculator():
    """Create bundle discount calculator."""
    return BundleDiscountCalculator()


@pytest.fixture
def fare_rules():
    """Create fare rule engine."""
    engine = FareRuleEngine()
    engine.define_fare_rules(
        "BASIC",
        is_refundable=False,
        change_fee=Decimal("50"),
        cancellation_penalty=Decimal("100"),
    )
    engine.define_fare_rules(
        "FLEX",
        is_refundable=True,
        change_fee=Decimal("0"),
        cancellation_penalty=Decimal("0"),
    )
    return engine


class TestDemandForecast:
    """Test demand forecasting."""

    def test_forecast_demand(self, demand_forecast):
        """Test forecasting demand."""
        demand = demand_forecast.forecast_demand("JFK", "LAX", date.today(), 30)
        assert 0.0 <= demand <= 2.0

    def test_demand_increases_with_proximity(self, demand_forecast):
        """Test that demand increases as departure approaches."""
        demand_far = demand_forecast.forecast_demand("JFK", "LAX", date.today(), 60)
        demand_near = demand_forecast.forecast_demand("JFK", "LAX", date.today(), 7)

        assert demand_near > demand_far

    def test_set_historical_occupancy(self, demand_forecast):
        """Test setting historical occupancy."""
        demand_forecast.set_historical_occupancy("JFK", "LAX", 1, 0.75)
        demand = demand_forecast.forecast_demand("JFK", "LAX", date.today(), 30)

        assert demand > 0


class TestPriceElasticity:
    """Test price elasticity modeling."""

    def test_calculate_quantity_change(self):
        """Test calculating quantity change from price change."""
        change = PriceElasticityModel.calculate_quantity_change(-0.1)
        assert change > 0  # Price decrease increases quantity

    def test_optimal_price_high_occupancy(self):
        """Test pricing at high occupancy."""
        base = Decimal("100")
        optimal = PriceElasticityModel.optimal_price(base, 0.90)
        assert optimal > base

    def test_optimal_price_low_occupancy(self):
        """Test pricing at low occupancy."""
        base = Decimal("100")
        optimal = PriceElasticityModel.optimal_price(base, 0.30)
        assert optimal < base


class TestYieldManagement:
    """Test yield management system."""

    def test_initialize_flight(self, yield_system):
        """Test initializing flight inventory."""
        capacity = {FareClass.ECONOMY: 100, FareClass.BUSINESS: 20}
        prices = {
            FareClass.ECONOMY: Decimal("250"),
            FareClass.BUSINESS: Decimal("800"),
        }

        yield_system.initialize_flight("AA100", capacity, prices)
        assert yield_system.get_availability_fraction("AA100", FareClass.ECONOMY) == 1.0

    def test_get_availability_fraction(self, yield_system):
        """Test getting availability fraction."""
        capacity = {FareClass.ECONOMY: 100}
        prices = {FareClass.ECONOMY: Decimal("250")}

        yield_system.initialize_flight("AA100", capacity, prices)
        yield_system.record_sale("AA100", FareClass.ECONOMY)

        availability = yield_system.get_availability_fraction("AA100", FareClass.ECONOMY)
        assert availability == 0.99

    def test_calculate_dynamic_price(self, yield_system):
        """Test calculating dynamic price."""
        capacity = {FareClass.ECONOMY: 100}
        prices = {FareClass.ECONOMY: Decimal("250")}

        yield_system.initialize_flight("AA100", capacity, prices)

        # No sales, should be discounted
        price1 = yield_system.calculate_dynamic_price("AA100", FareClass.ECONOMY, 60)

        # After sales, should be higher
        for _ in range(90):
            yield_system.record_sale("AA100", FareClass.ECONOMY)

        price2 = yield_system.calculate_dynamic_price("AA100", FareClass.ECONOMY, 3)

        assert price2 > price1

    def test_advance_purchase_discount(self, yield_system):
        """Test advance purchase pricing discount."""
        capacity = {FareClass.ECONOMY: 100}
        prices = {FareClass.ECONOMY: Decimal("250")}

        yield_system.initialize_flight("AA100", capacity, prices)

        # 60 days advance
        price_60 = yield_system.calculate_dynamic_price("AA100", FareClass.ECONOMY, 60)

        # 3 days advance
        price_3 = yield_system.calculate_dynamic_price("AA100", FareClass.ECONOMY, 3)

        assert price_60 < price_3


class TestCurrencyConverter:
    """Test currency conversion."""

    def test_convert_same_currency(self, currency_converter):
        """Test converting to same currency."""
        amount = Decimal("100")
        result = currency_converter.convert(amount, Currency.USD, Currency.USD)
        assert result == amount

    def test_convert_usd_to_eur(self, currency_converter):
        """Test converting USD to EUR."""
        amount = Decimal("100")
        result = currency_converter.convert(amount, Currency.USD, Currency.EUR)

        assert result < amount  # EUR is stronger

    def test_set_exchange_rate(self, currency_converter):
        """Test setting custom exchange rate."""
        currency_converter.set_exchange_rate(Currency.USD, Currency.GBP, Decimal("0.80"))
        result = currency_converter.convert(Decimal("100"), Currency.USD, Currency.GBP)
        assert result == Decimal("80")

    def test_missing_exchange_rate(self, currency_converter):
        """Test error for missing exchange rate."""
        # Currency not in default rates
        currency_converter._exchange_rates.clear()

        with pytest.raises(CurrencyConversionError):
            currency_converter.convert(Decimal("100"), Currency.USD, Currency.EUR)


class TestPriceComparison:
    """Test price comparison engine."""

    def test_record_price(self, comparison_engine):
        """Test recording competitor prices."""
        comparison_engine.record_price("JFK-LAX", "AA", Decimal("250"))
        comparison_engine.record_price("JFK-LAX", "UA", Decimal("280"))

        provider, price = comparison_engine.get_best_price("JFK-LAX")
        assert provider == "AA"
        assert price == Decimal("250")

    def test_get_price_range(self, comparison_engine):
        """Test getting price range."""
        comparison_engine.record_price("JFK-LAX", "AA", Decimal("200"))
        comparison_engine.record_price("JFK-LAX", "UA", Decimal("300"))

        min_price, max_price = comparison_engine.get_price_range("JFK-LAX")
        assert min_price == Decimal("200")
        assert max_price == Decimal("300")


class TestBundleDiscount:
    """Test bundle discount calculator."""

    def test_flight_hotel_bundle(self, bundle_calculator):
        """Test flight + hotel bundle discount."""
        flight = Decimal("250")
        hotel = Decimal("500")

        bundled = bundle_calculator.calculate_package_discount(flight, hotel)
        assert bundled < flight + hotel

    def test_flight_hotel_car_bundle(self, bundle_calculator):
        """Test flight + hotel + car bundle discount."""
        flight = Decimal("250")
        hotel = Decimal("500")
        car = Decimal("200")

        bundled = bundle_calculator.calculate_package_discount(flight, hotel, car)
        assert bundled < flight + hotel + car

    def test_get_savings(self, bundle_calculator):
        """Test calculating savings amount."""
        flight = Decimal("250")
        hotel = Decimal("500")

        savings = bundle_calculator.get_savings(flight, hotel)
        assert savings > 0

    def test_car_bundle_larger_discount(self, bundle_calculator):
        """Test that 3-way bundle has larger discount than 2-way."""
        flight = Decimal("250")
        hotel = Decimal("500")
        car = Decimal("200")

        savings_2way = bundle_calculator.get_savings(flight, hotel)
        savings_3way = bundle_calculator.get_savings(flight, hotel, car)

        assert savings_3way > savings_2way


class TestFareRules:
    """Test fare rule engine."""

    def test_define_fare_rules(self, fare_rules):
        """Test defining fare rules."""
        rules = fare_rules.get_fare_rules("BASIC")
        assert rules["refundable"] is False
        assert rules["change_fee"] == Decimal("50")

    def test_calculate_refund_refundable(self, fare_rules):
        """Test refund calculation for refundable fare."""
        original = Decimal("500")
        refund = fare_rules.calculate_refund("FLEX", original, is_cancellation=True)

        # Fully refundable
        assert refund == original

    def test_calculate_refund_non_refundable(self, fare_rules):
        """Test refund for non-refundable fare."""
        original = Decimal("500")
        refund = fare_rules.calculate_refund("BASIC", original, is_cancellation=True)

        # No refund, just deduct penalty
        assert refund < original

    def test_calculate_refund_change_fee(self, fare_rules):
        """Test refund calculation for date change."""
        original = Decimal("500")
        refund = fare_rules.calculate_refund("FLEX", original, is_cancellation=False)

        # Flex is free to change
        assert refund == original


class TestPricingIntegration:
    """Integration tests for pricing operations."""

    def test_dynamic_pricing_scenario(self, yield_system):
        """Test complete dynamic pricing scenario."""
        # Initialize flight
        capacity = {FareClass.ECONOMY: 100}
        prices = {FareClass.ECONOMY: Decimal("250")}
        yield_system.initialize_flight("AA100", capacity, prices)

        # Day 1: 60 days before, low demand
        price_day1 = yield_system.calculate_dynamic_price("AA100", FareClass.ECONOMY, 60)

        # Simulate sales
        for _ in range(80):
            yield_system.record_sale("AA100", FareClass.ECONOMY)

        # Day 2: 3 days before, high demand
        price_day2 = yield_system.calculate_dynamic_price("AA100", FareClass.ECONOMY, 3)

        # Price should increase as departure approaches and seats fill
        assert price_day2 > price_day1
