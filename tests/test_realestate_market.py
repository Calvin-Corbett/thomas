"""Tests for market analysis module."""

from datetime import date
from decimal import Decimal

import pytest

from thomas.marketplace.real_estate._exceptions import InsufficientDataError
from thomas.marketplace.real_estate._types import MarketStats
from thomas.marketplace.real_estate.market import (
    InventoryAnalysis,
    MarketForecast,
    MarketIndicators,
    MarketStatistics,
    NeighborhoodComparison,
    PriceTrendAnalysis,
    RentalYieldAnalysis,
    SupplyDemandIndicators,
)


class TestMarketStatistics:
    """Test market statistics calculations."""

    def test_median_price(self):
        """Test median price calculation."""
        prices = [Decimal("400000"), Decimal("500000"), Decimal("600000")]
        median = MarketStatistics.calculate_median_price(prices)
        assert median == Decimal("500000")

    def test_insufficient_prices_raises_error(self):
        """Test insufficient prices raises error."""
        prices = [Decimal("400000"), Decimal("500000")]
        with pytest.raises(InsufficientDataError):
            MarketStatistics.calculate_median_price(prices)

    def test_average_price(self):
        """Test average price calculation."""
        prices = [Decimal("400000"), Decimal("500000"), Decimal("600000")]
        avg = MarketStatistics.calculate_average_price(prices)
        assert avg == Decimal("500000")

    def test_price_per_sqft(self):
        """Test average price per square foot."""
        prices = [Decimal("400000"), Decimal("500000"), Decimal("600000")]
        sqfts = [2000, 2500, 3000]
        ppsf = MarketStatistics.calculate_price_per_sqft(prices, sqfts)
        assert ppsf > Decimal("0")

    def test_median_dom(self):
        """Test median days on market."""
        doms = [30, 45, 60, 50, 40]
        median_dom = MarketStatistics.calculate_median_dom(doms)
        assert median_dom == 45


class TestInventoryAnalysis:
    """Test inventory analysis."""

    def test_months_of_supply(self):
        """Test months of supply calculation."""
        mos = InventoryAnalysis.calculate_months_of_supply(100, 50)
        assert mos == Decimal("2")

    def test_market_type_sellers(self):
        """Test sellers market classification."""
        market_type = InventoryAnalysis.market_type_classification(Decimal("1.5"))
        assert market_type == "sellers_market"

    def test_market_type_buyers(self):
        """Test buyers market classification."""
        market_type = InventoryAnalysis.market_type_classification(Decimal("8"))
        assert market_type == "buyers_market"

    def test_market_type_balanced(self):
        """Test balanced market classification."""
        market_type = InventoryAnalysis.market_type_classification(Decimal("4"))
        assert market_type == "balanced"

    def test_inventory_percentage_change(self):
        """Test inventory change calculation."""
        change = InventoryAnalysis.calculate_inventory_percentage_change(100, 80)
        assert change == Decimal("0.25")


class TestPriceTrendAnalysis:
    """Test price trend analysis."""

    def test_simple_moving_average(self):
        """Test simple moving average."""
        prices = [
            Decimal("400000"),
            Decimal("410000"),
            Decimal("420000"),
            Decimal("430000"),
        ]
        ma = PriceTrendAnalysis.simple_moving_average(prices, 2)
        assert len(ma) == 3
        assert ma[0] == Decimal("405000")

    def test_linear_trend(self):
        """Test linear trend calculation."""
        prices = [
            Decimal("400000"),
            Decimal("410000"),
            Decimal("420000"),
        ]
        slope, intercept = PriceTrendAnalysis.linear_trend(prices)
        assert slope > Decimal("0")

    def test_yoy_appreciation(self):
        """Test year-over-year appreciation."""
        appreciation = PriceTrendAnalysis.year_over_year_appreciation(Decimal("520000"), Decimal("500000"))
        assert appreciation == Decimal("0.04")


class TestMarketIndicators:
    """Test market health indicators."""

    def test_price_to_rent_ratio(self):
        """Test price-to-rent ratio."""
        ratio = MarketIndicators.price_to_rent_ratio(Decimal("500000"), Decimal("60000"))
        assert ratio == pytest.approx(Decimal("8.333"), abs=Decimal("0.01"))

    def test_affordability_index(self):
        """Test affordability index."""
        index = MarketIndicators.affordability_index(Decimal("500000"), Decimal("75000"))
        assert index > Decimal("0")

    def test_affordability_index_unaffordable(self):
        """Test affordability index for unaffordable market."""
        index = MarketIndicators.affordability_index(Decimal("800000"), Decimal("50000"))
        assert index < Decimal("100")


class TestNeighborhoodComparison:
    """Test neighborhood comparison."""

    def setup_method(self):
        """Set up test fixtures."""
        self.market1 = MarketStats(
            market_id="mkt1",
            area_name="Area 1",
            statistic_date=date.today(),
            median_price=Decimal("500000"),
            average_price=Decimal("520000"),
            median_sqft=2000,
            active_listings=100,
            pending_listings=20,
            sold_listings_count=50,
            median_dom=45,
            inventory_months=Decimal("2.4"),
            price_per_sqft=Decimal("250"),
        )
        self.market2 = MarketStats(
            market_id="mkt2",
            area_name="Area 2",
            statistic_date=date.today(),
            median_price=Decimal("450000"),
            average_price=Decimal("470000"),
            median_sqft=1900,
            active_listings=80,
            pending_listings=15,
            sold_listings_count=60,
            median_dom=35,
            inventory_months=Decimal("1.6"),
            price_per_sqft=Decimal("240"),
        )

    def test_compare_markets(self):
        """Test comparing two markets."""
        comparison = NeighborhoodComparison.compare_markets(self.market1, self.market2)
        assert comparison["median_price_diff"] == Decimal("50000")

    def test_rank_markets(self):
        """Test ranking markets by appreciation."""
        market1 = MarketStats(
            market_id="mkt1",
            area_name="Growing Area",
            statistic_date=date.today(),
            median_price=Decimal("500000"),
            average_price=Decimal("520000"),
            median_sqft=2000,
            active_listings=100,
            pending_listings=20,
            sold_listings_count=50,
            median_dom=45,
            inventory_months=Decimal("2"),
            price_per_sqft=Decimal("250"),
            appreciation_rate=Decimal("0.05"),
        )
        market2 = MarketStats(
            market_id="mkt2",
            area_name="Stable Area",
            statistic_date=date.today(),
            median_price=Decimal("450000"),
            average_price=Decimal("470000"),
            median_sqft=1900,
            active_listings=80,
            pending_listings=15,
            sold_listings_count=60,
            median_dom=35,
            inventory_months=Decimal("1.6"),
            price_per_sqft=Decimal("240"),
            appreciation_rate=Decimal("0.02"),
        )
        ranked = NeighborhoodComparison.rank_markets_by_appreciation([market2, market1])
        assert ranked[0][0] == "Growing Area"


class TestRentalYieldAnalysis:
    """Test rental yield analysis."""

    def test_gross_rental_yield(self):
        """Test gross rental yield."""
        yield_rate = RentalYieldAnalysis.gross_rental_yield(Decimal("60000"), Decimal("500000"))
        assert yield_rate == Decimal("0.12")

    def test_net_rental_yield(self):
        """Test net rental yield."""
        yield_rate = RentalYieldAnalysis.net_rental_yield(
            Decimal("60000"),
            Decimal("15000"),
            Decimal("500000"),
        )
        assert yield_rate == Decimal("0.09")

    def test_grm(self):
        """Test gross rent multiplier."""
        grm = RentalYieldAnalysis.gross_rent_multiplier(Decimal("500000"), Decimal("60000"))
        assert grm == pytest.approx(Decimal("8.333"), abs=Decimal("0.01"))


class TestSupplyDemandIndicators:
    """Test supply and demand indicators."""

    def test_sold_percentage(self):
        """Test sold percentage."""
        sold_pct = SupplyDemandIndicators.calculate_sold_percentage(85, 100)
        assert sold_pct == Decimal("0.85")

    def test_withdrawal_rate(self):
        """Test withdrawal rate."""
        rate = SupplyDemandIndicators.calculate_withdrawal_rate(10, 100)
        assert rate == Decimal("0.1")

    def test_new_to_sold_ratio(self):
        """Test new to sold ratio."""
        ratio = SupplyDemandIndicators.new_to_sold_ratio(100, 50)
        assert ratio == Decimal("2")

    def test_new_to_sold_ratio_no_sales(self):
        """Test new to sold ratio with no sales."""
        ratio = SupplyDemandIndicators.new_to_sold_ratio(100, 0)
        assert ratio is None


class TestMarketForecast:
    """Test market forecasting."""

    def test_simple_trend_forecast(self):
        """Test simple trend forecasting."""
        historical = [
            (date(2020, 1, 1), Decimal("400000")),
            (date(2021, 1, 1), Decimal("420000")),
            (date(2022, 1, 1), Decimal("440000")),
        ]
        forecast = MarketForecast.simple_trend_forecast(historical, 2)
        assert len(forecast) == 2
        assert forecast[0][1] > Decimal("440000")

    def test_insufficient_historical_data_raises_error(self):
        """Test insufficient historical data raises error."""
        historical = [(date(2020, 1, 1), Decimal("400000"))]
        with pytest.raises(InsufficientDataError):
            MarketForecast.simple_trend_forecast(historical, 2)

    def test_seasonal_adjustment(self):
        """Test seasonal adjustment."""
        monthly_prices = [
            Decimal("400000"),
            Decimal("410000"),
            Decimal("420000"),
            Decimal("430000"),
            Decimal("420000"),
            Decimal("410000"),
            Decimal("400000"),
            Decimal("410000"),
            Decimal("420000"),
            Decimal("430000"),
            Decimal("420000"),
            Decimal("410000"),
        ]
        factors = MarketForecast.seasonal_adjustment(monthly_prices)
        assert len(factors) == 12
        assert all(f > Decimal("0") for f in factors)
