"""Market analysis and statistics."""

import statistics
from datetime import date, timedelta
from decimal import Decimal

from thomas.real_estate._exceptions import InsufficientDataError
from thomas.real_estate._types import MarketStats


class MarketStatistics:
    """Market statistics calculation and analysis."""

    @staticmethod
    def calculate_median_price(prices: list[Decimal]) -> Decimal:
        """Calculate median property price.

        Args:
            prices: List of property prices

        Returns:
            Median price

        Raises:
            InsufficientDataError: If fewer than 3 prices
        """
        if len(prices) < 3:
            raise InsufficientDataError("Need at least 3 prices for median")
        return Decimal(statistics.median(prices))

    @staticmethod
    def calculate_average_price(prices: list[Decimal]) -> Decimal:
        """Calculate average property price.

        Args:
            prices: List of property prices

        Returns:
            Average price
        """
        if not prices:
            return Decimal("0")
        return Decimal(statistics.mean(prices))

    @staticmethod
    def calculate_price_per_sqft(prices: list[Decimal], sqfts: list[int]) -> Decimal:
        """Calculate average price per square foot.

        Args:
            prices: List of property prices
            sqfts: List of property square footages

        Returns:
            Average price per square foot
        """
        if not prices or len(prices) != len(sqfts):
            return Decimal("0")

        total_price = sum(prices)
        total_sqft = sum(sqfts)

        if total_sqft == 0:
            return Decimal("0")

        return total_price / Decimal(total_sqft)

    @staticmethod
    def calculate_median_dom(days_on_markets: list[int]) -> float:
        """Calculate median days on market.

        Args:
            days_on_markets: List of DOM values

        Returns:
            Median DOM
        """
        if not days_on_markets:
            return 0.0
        return statistics.median(days_on_markets)


class InventoryAnalysis:
    """Inventory and supply analysis."""

    @staticmethod
    def calculate_months_of_supply(active_listings: int, monthly_sold_average: int) -> Decimal:
        """Calculate months of inventory (absorption rate).

        Months of Supply = Active Listings / Monthly Sales Average

        Args:
            active_listings: Number of active listings
            monthly_sold_average: Average monthly sales

        Returns:
            Months of inventory

        Raises:
            ValueError: If monthly_sold_average is zero
        """
        if monthly_sold_average == 0:
            raise ValueError("Monthly sales average must be non-zero")

        return Decimal(active_listings) / Decimal(monthly_sold_average)

    @staticmethod
    def market_type_classification(
        months_of_supply: Decimal,
    ) -> str:
        """Classify market as buyers, balanced, or sellers market.

        Args:
            months_of_supply: Months of inventory

        Returns:
            Market type: "buyers_market", "balanced", or "sellers_market"
        """
        if months_of_supply > Decimal("6"):
            return "buyers_market"
        elif months_of_supply < Decimal("2"):
            return "sellers_market"
        else:
            return "balanced"

    @staticmethod
    def calculate_inventory_percentage_change(current_inventory: int, previous_inventory: int) -> Decimal:
        """Calculate inventory percentage change.

        Args:
            current_inventory: Current active listings
            previous_inventory: Previous period active listings

        Returns:
            Percentage change (e.g., -0.10 for 10% decrease)
        """
        if previous_inventory == 0:
            return Decimal("0")

        change = (current_inventory - previous_inventory) / previous_inventory
        return change


class PriceTrendAnalysis:
    """Price trend and appreciation analysis."""

    @staticmethod
    def simple_moving_average(prices: list[Decimal], window: int = 3) -> list[Decimal]:
        """Calculate simple moving average of prices.

        Args:
            prices: List of price data points
            window: Moving average window (default 3)

        Returns:
            List of moving averages
        """
        if len(prices) < window:
            return []

        moving_avg = []
        for i in range(len(prices) - window + 1):
            window_prices = prices[i : i + window]
            avg = sum(window_prices) / Decimal(window)
            moving_avg.append(avg)

        return moving_avg

    @staticmethod
    def linear_trend(
        prices: list[Decimal],
    ) -> tuple[Decimal, Decimal]:
        """Calculate linear trend of prices.

        Args:
            prices: List of price data points

        Returns:
            Tuple of (slope, intercept)
        """
        if len(prices) < 2:
            return (Decimal("0"), Decimal("0"))

        n = len(prices)
        x_mean = Decimal(n - 1) / Decimal(2)
        y_mean = sum(prices) / Decimal(n)

        numerator = Decimal("0")
        denominator = Decimal("0")

        for i, price in enumerate(prices):
            x_diff = Decimal(i) - x_mean
            y_diff = price - y_mean
            numerator += x_diff * y_diff
            denominator += x_diff * x_diff

        if denominator == 0:
            return (Decimal("0"), y_mean)

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        return (slope, intercept)

    @staticmethod
    def year_over_year_appreciation(current_price: Decimal, price_one_year_ago: Decimal) -> Decimal:
        """Calculate year-over-year appreciation rate.

        Args:
            current_price: Current price
            price_one_year_ago: Price one year ago

        Returns:
            Appreciation rate (e.g., 0.05 for 5%)
        """
        if price_one_year_ago == 0:
            return Decimal("0")

        return (current_price - price_one_year_ago) / price_one_year_ago


class MarketIndicators:
    """Market health indicators and metrics."""

    @staticmethod
    def price_to_rent_ratio(median_price: Decimal, annual_rental_income: Decimal) -> Decimal:
        """Calculate price-to-rent ratio.

        Higher ratio indicates buyers market, lower indicates renters market.

        Args:
            median_price: Median property price
            annual_rental_income: Annual rental income

        Returns:
            Price-to-rent ratio

        Raises:
            ValueError: If annual_rental_income is zero
        """
        if annual_rental_income == 0:
            raise ValueError("Annual rental income must be non-zero")

        return median_price / annual_rental_income

    @staticmethod
    def affordability_index(
        median_price: Decimal,
        median_household_income: Decimal,
        down_payment_percentage: Decimal = Decimal("0.20"),
        interest_rate: Decimal = Decimal("0.065"),
    ) -> Decimal:
        """Calculate housing affordability index.

        Index > 100 = more affordable, < 100 = less affordable

        Args:
            median_price: Median property price
            median_household_income: Median household income
            down_payment_percentage: Down payment percentage
            interest_rate: Mortgage interest rate

        Returns:
            Affordability index
        """
        loan_amount = median_price * (1 - down_payment_percentage)
        monthly_rate = interest_rate / Decimal(12)
        term_months = 360

        if monthly_rate == 0:
            monthly_payment = loan_amount / Decimal(term_months)
        else:
            numerator = monthly_rate * ((1 + monthly_rate) ** term_months)
            denominator = ((1 + monthly_rate) ** term_months) - 1
            monthly_payment = loan_amount * (numerator / denominator)

        required_income = monthly_payment * Decimal(12) / Decimal("0.28")

        if required_income == 0:
            return Decimal("0")

        index = (median_household_income / required_income) * Decimal("100")
        return index


class NeighborhoodComparison:
    """Neighborhood-level comparison analysis."""

    @staticmethod
    def compare_markets(market_stats_1: MarketStats, market_stats_2: MarketStats) -> dict[str, Decimal]:
        """Compare two market areas.

        Args:
            market_stats_1: First market statistics
            market_stats_2: Second market statistics

        Returns:
            Dictionary of comparison metrics
        """
        return {
            "median_price_diff": market_stats_1.median_price - market_stats_2.median_price,
            "price_per_sqft_diff": market_stats_1.price_per_sqft - market_stats_2.price_per_sqft,
            "inventory_diff": Decimal(market_stats_1.active_listings) - Decimal(market_stats_2.active_listings),
            "dom_diff": Decimal(market_stats_1.median_dom) - Decimal(market_stats_2.median_dom),
        }

    @staticmethod
    def rank_markets_by_appreciation(
        market_stats_list: list[MarketStats],
    ) -> list[tuple[str, Decimal]]:
        """Rank markets by appreciation rate.

        Args:
            market_stats_list: List of market statistics

        Returns:
            List of (market_name, appreciation_rate) sorted by rate descending
        """
        ranked = [(m.area_name, m.appreciation_rate) for m in market_stats_list]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked


class RentalYieldAnalysis:
    """Rental yield and income analysis."""

    @staticmethod
    def gross_rental_yield(annual_rent: Decimal, property_value: Decimal) -> Decimal:
        """Calculate gross rental yield.

        Gross Yield = Annual Rent / Property Value

        Args:
            annual_rent: Annual rental income
            property_value: Property value

        Returns:
            Gross yield (e.g., 0.05 for 5%)

        Raises:
            ValueError: If property_value is zero
        """
        if property_value == 0:
            raise ValueError("Property value must be non-zero")

        return annual_rent / property_value

    @staticmethod
    def net_rental_yield(
        annual_rent: Decimal,
        annual_expenses: Decimal,
        property_value: Decimal,
    ) -> Decimal:
        """Calculate net rental yield.

        Net Yield = (Annual Rent - Annual Expenses) / Property Value

        Args:
            annual_rent: Annual rental income
            annual_expenses: Annual expenses (taxes, insurance, maintenance)
            property_value: Property value

        Returns:
            Net yield (e.g., 0.04 for 4%)

        Raises:
            ValueError: If property_value is zero
        """
        if property_value == 0:
            raise ValueError("Property value must be non-zero")

        net_income = annual_rent - annual_expenses
        return net_income / property_value

    @staticmethod
    def gross_rent_multiplier(property_price: Decimal, annual_rent: Decimal) -> Decimal:
        """Calculate gross rent multiplier.

        GRM = Property Price / Annual Rent
        Lower GRM = better investment in theory.

        Args:
            property_price: Property price
            annual_rent: Annual rental income

        Returns:
            Gross rent multiplier

        Raises:
            ValueError: If annual_rent is zero
        """
        if annual_rent == 0:
            raise ValueError("Annual rent must be non-zero")

        return property_price / annual_rent


class SupplyDemandIndicators:
    """Supply and demand indicators."""

    @staticmethod
    def calculate_sold_percentage(sold_listings: int, total_listings: int) -> Decimal:
        """Calculate percentage of listings that sold.

        Args:
            sold_listings: Number of sold listings
            total_listings: Total listings

        Returns:
            Percentage (e.g., 0.85 for 85%)
        """
        if total_listings == 0:
            return Decimal("0")

        return Decimal(sold_listings) / Decimal(total_listings)

    @staticmethod
    def calculate_withdrawal_rate(withdrawn_listings: int, total_listings: int) -> Decimal:
        """Calculate percentage of withdrawn listings.

        Args:
            withdrawn_listings: Number of withdrawn listings
            total_listings: Total listings

        Returns:
            Withdrawal rate (e.g., 0.10 for 10%)
        """
        if total_listings == 0:
            return Decimal("0")

        return Decimal(withdrawn_listings) / Decimal(total_listings)

    @staticmethod
    def new_to_sold_ratio(new_listings: int, sold_listings: int) -> Decimal | None:
        """Calculate new listings to sold listings ratio.

        Args:
            new_listings: New listings this period
            sold_listings: Sold listings this period

        Returns:
            Ratio or None if no sold listings
        """
        if sold_listings == 0:
            return None

        return Decimal(new_listings) / Decimal(sold_listings)


class MarketForecast:
    """Market trend forecasting."""

    @staticmethod
    def simple_trend_forecast(
        historical_prices: list[tuple[date, Decimal]], forecast_months: int
    ) -> list[tuple[date, Decimal]]:
        """Forecast prices using simple linear trend.

        Args:
            historical_prices: List of (date, price) tuples
            forecast_months: Number of months to forecast

        Returns:
            List of (forecast_date, predicted_price) tuples
        """
        if len(historical_prices) < 2:
            raise InsufficientDataError("Need at least 2 historical data points")

        prices = [p for _, p in historical_prices]
        dates = [d for d, _ in historical_prices]

        x_values = [(dates[i] - dates[0]).days / 30.0 for i in range(len(dates))]
        y_values = [float(p) for p in prices]

        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(y_values)

        numerator = sum((x_values[i] - x_mean) * (y_values[i] - y_mean) for i in range(len(x_values)))
        denominator = sum((x_values[i] - x_mean) ** 2 for i in range(len(x_values)))

        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator

        intercept = y_mean - slope * x_mean

        forecasts = []
        last_date = dates[-1]

        for month in range(1, forecast_months + 1):
            forecast_date = last_date + timedelta(days=month * 30)
            days_out = (forecast_date - dates[0]).days / 30.0
            forecast_price = Decimal(str(intercept + slope * days_out))
            forecasts.append((forecast_date, forecast_price))

        return forecasts

    @staticmethod
    def seasonal_adjustment(
        monthly_prices: list[Decimal],
    ) -> list[Decimal]:
        """Adjust prices for seasonal trends.

        Args:
            monthly_prices: List of 12 monthly prices

        Returns:
            List of seasonal adjustment factors
        """
        if len(monthly_prices) < 12:
            return [Decimal("1")] * len(monthly_prices)

        annual_mean = sum(monthly_prices) / Decimal(12)
        if annual_mean == 0:
            return [Decimal("1")] * 12

        factors = [price / annual_mean for price in monthly_prices]
        return factors
