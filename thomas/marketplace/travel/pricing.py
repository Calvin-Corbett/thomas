"""Dynamic pricing engine with yield management and price optimization."""

from datetime import date
from decimal import Decimal

from thomas.marketplace.travel._exceptions import CurrencyConversionError
from thomas.marketplace.travel._types import Currency, FareClass


class DemandForecast:
    """Forecast demand for flights using historical data."""

    def __init__(self) -> None:
        """Initialize demand forecaster."""
        self._historical_occupancy: dict[tuple[str, str, int], float] = {}
        self._booking_curve: dict[int, float] = {}  # days_advance -> pct_sold

        # Load default booking curve (more demand closer to departure)
        self._booking_curve = {
            60: 0.20,
            30: 0.50,
            14: 0.75,
            7: 0.90,
            3: 0.98,
        }

    def forecast_demand(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        days_advance: int,
    ) -> float:
        """
        Forecast demand multiplier for flight.

        Args:
            origin: Origin airport code
            destination: Destination airport code
            departure_date: Departure date
            days_advance: Days in advance of booking

        Returns:
            Demand multiplier (1.0 = baseline)
        """
        # Get historical occupancy
        day_of_week = departure_date.weekday()
        key = (origin, destination, day_of_week)
        base_occupancy = self._historical_occupancy.get(key, 0.65)

        # Get booking curve percentage
        booked_pct = 0.5
        for days, pct in sorted(self._booking_curve.items(), reverse=True):
            if days_advance <= days:
                booked_pct = pct
                break

        # Combine factors
        demand_multiplier = base_occupancy * (booked_pct + 0.3)
        return min(demand_multiplier, 2.0)  # Cap at 2x

    def set_historical_occupancy(
        self,
        origin: str,
        destination: str,
        day_of_week: int,
        occupancy: float,
    ) -> None:
        """
        Set historical occupancy rate.

        Args:
            origin: Origin airport code
            destination: Destination airport code
            day_of_week: Day of week (0=Monday)
            occupancy: Occupancy rate (0.0-1.0)
        """
        key = (origin, destination, day_of_week)
        self._historical_occupancy[key] = occupancy


class PriceElasticityModel:
    """Model price elasticity of demand."""

    # Elasticity coefficient (higher = more elastic)
    ELASTICITY_COEFFICIENT = 1.5

    @staticmethod
    def calculate_quantity_change(
        price_change_pct: float,
        elasticity: float = ELASTICITY_COEFFICIENT,
    ) -> float:
        """
        Calculate quantity change from price change using elasticity.

        Args:
            price_change_pct: Price change percentage (-0.5 = 50% decrease)
            elasticity: Price elasticity coefficient

        Returns:
            Expected quantity change percentage
        """
        # Quantity change = elasticity * price change percentage
        return elasticity * price_change_pct

    @staticmethod
    def optimal_price(
        base_price: Decimal,
        occupancy: float,
        elasticity: float = ELASTICITY_COEFFICIENT,
    ) -> Decimal:
        """
        Calculate optimal price based on occupancy and elasticity.

        Args:
            base_price: Base price
            occupancy: Current occupancy rate (0.0-1.0)
            elasticity: Price elasticity

        Returns:
            Optimized price
        """
        # Higher occupancy = higher price, lower occupancy = lower price
        if occupancy > 0.85:
            price_multiplier = 1.25  # 25% premium
        elif occupancy > 0.70:
            price_multiplier = 1.10  # 10% premium
        elif occupancy > 0.50:
            price_multiplier = 1.0  # Standard price
        else:
            price_multiplier = 0.85  # 15% discount

        return base_price * Decimal(price_multiplier)


class YieldManagementSystem:
    """Yield management for dynamic pricing."""

    def __init__(self) -> None:
        """Initialize yield management system."""
        self._capacity_by_class: dict[str, dict[FareClass, int]] = {}
        self._sold_by_class: dict[str, dict[FareClass, int]] = {}
        self._base_prices: dict[str, dict[FareClass, Decimal]] = {}
        self._current_prices: dict[str, dict[FareClass, Decimal]] = {}
        self.demand_forecast = DemandForecast()

    def initialize_flight(
        self,
        flight_id: str,
        capacity_by_class: dict[FareClass, int],
        base_prices: dict[FareClass, Decimal],
    ) -> None:
        """
        Initialize flight inventory.

        Args:
            flight_id: Flight identifier
            capacity_by_class: Capacity by fare class
            base_prices: Base prices by fare class
        """
        self._capacity_by_class[flight_id] = capacity_by_class.copy()
        self._base_prices[flight_id] = base_prices.copy()
        self._current_prices[flight_id] = base_prices.copy()
        self._sold_by_class[flight_id] = {fc: 0 for fc in capacity_by_class}

    def get_availability_fraction(
        self,
        flight_id: str,
        fare_class: FareClass,
    ) -> float:
        """
        Get fraction of capacity available.

        Args:
            flight_id: Flight identifier
            fare_class: Fare class

        Returns:
            Availability fraction (0.0-1.0)
        """
        capacity = self._capacity_by_class.get(flight_id, {}).get(fare_class, 0)
        sold = self._sold_by_class.get(flight_id, {}).get(fare_class, 0)

        if capacity == 0:
            return 0.0

        return 1.0 - (sold / capacity)

    def calculate_dynamic_price(
        self,
        flight_id: str,
        fare_class: FareClass,
        days_advance: int,
    ) -> Decimal:
        """
        Calculate dynamic price for fare class.

        Args:
            flight_id: Flight identifier
            fare_class: Fare class
            days_advance: Days in advance

        Returns:
            Dynamic price
        """
        base_price = self._base_prices.get(flight_id, {}).get(fare_class, Decimal("100"))
        availability = self.get_availability_fraction(flight_id, fare_class)

        # Price multiplier based on availability
        if availability < 0.05:
            multiplier = 2.0  # Very scarce
        elif availability < 0.15:
            multiplier = 1.75
        elif availability < 0.25:
            multiplier = 1.50
        elif availability < 0.40:
            multiplier = 1.25
        elif availability < 0.60:
            multiplier = 1.0
        elif availability < 0.80:
            multiplier = 0.90
        else:
            multiplier = 0.75

        # Advance purchase discount
        if days_advance >= 60:
            multiplier *= 0.75
        elif days_advance >= 30:
            multiplier *= 0.85
        elif days_advance >= 14:
            multiplier *= 0.95

        price = base_price * Decimal(multiplier)
        self._current_prices[flight_id][fare_class] = price
        return price

    def record_sale(self, flight_id: str, fare_class: FareClass) -> None:
        """
        Record fare class sale.

        Args:
            flight_id: Flight identifier
            fare_class: Fare class
        """
        if flight_id not in self._sold_by_class:
            return

        self._sold_by_class[flight_id][fare_class] += 1


class CurrencyConverter:
    """Currency conversion with exchange rates."""

    def __init__(self) -> None:
        """Initialize converter."""
        self._exchange_rates: dict[tuple[Currency, Currency], Decimal] = {}
        self._load_default_rates()

    def _load_default_rates(self) -> None:
        """Load default exchange rates (as of Feb 2025)."""
        rates = {
            (Currency.USD, Currency.EUR): Decimal("0.92"),
            (Currency.USD, Currency.GBP): Decimal("0.79"),
            (Currency.USD, Currency.JPY): Decimal("155.00"),
            (Currency.USD, Currency.AUD): Decimal("1.56"),
            (Currency.USD, Currency.CAD): Decimal("1.38"),
            (Currency.EUR, Currency.USD): Decimal("1.09"),
            (Currency.GBP, Currency.USD): Decimal("1.27"),
            (Currency.JPY, Currency.USD): Decimal("0.0065"),
        }

        for (from_curr, to_curr), rate in rates.items():
            self._exchange_rates[(from_curr, to_curr)] = rate

        # Add identity conversions
        for currency in Currency:
            self._exchange_rates[(currency, currency)] = Decimal("1.0")

    def set_exchange_rate(
        self,
        from_currency: Currency,
        to_currency: Currency,
        rate: Decimal,
    ) -> None:
        """
        Set exchange rate.

        Args:
            from_currency: Source currency
            to_currency: Target currency
            rate: Exchange rate
        """
        self._exchange_rates[(from_currency, to_currency)] = rate

    def convert(
        self,
        amount: Decimal,
        from_currency: Currency,
        to_currency: Currency,
    ) -> Decimal:
        """
        Convert amount between currencies.

        Args:
            amount: Amount to convert
            from_currency: Source currency
            to_currency: Target currency

        Returns:
            Converted amount

        Raises:
            CurrencyConversionError: If conversion rate not available
        """
        if from_currency == to_currency:
            return amount

        rate = self._exchange_rates.get((from_currency, to_currency))
        if rate is None:
            raise CurrencyConversionError(f"No exchange rate for {from_currency.value} to {to_currency.value}")

        return amount * rate


class PriceComparisonEngine:
    """Compare prices across providers and routes."""

    def __init__(self) -> None:
        """Initialize comparison engine."""
        self._provider_prices: dict[str, dict[str, Decimal]] = {}

    def record_price(
        self,
        provider: str,
        route_id: str,
        price: Decimal,
    ) -> None:
        """
        Record price from provider.

        Args:
            provider: Provider name
            route_id: Route identifier
            price: Price offered
        """
        if provider not in self._provider_prices:
            self._provider_prices[provider] = {}

        self._provider_prices[provider][route_id] = price

    def get_best_price(self, route_id: str) -> tuple[str | None, Decimal | None]:
        """
        Get best price for route across providers.

        Args:
            route_id: Route identifier

        Returns:
            Tuple of (provider_name, price)
        """
        best_provider = None
        best_price = None

        for provider, prices in self._provider_prices.items():
            if route_id in prices:
                price = prices[route_id]
                if best_price is None or price < best_price:
                    best_price = price
                    best_provider = provider

        return best_provider, best_price

    def get_price_range(self, route_id: str) -> tuple[Decimal, Decimal]:
        """
        Get price range for route.

        Args:
            route_id: Route identifier

        Returns:
            Tuple of (min_price, max_price)
        """
        prices = []
        for provider_prices in self._provider_prices.values():
            if route_id in provider_prices:
                prices.append(provider_prices[route_id])

        if not prices:
            return Decimal("0"), Decimal("0")

        return min(prices), max(prices)


class BundleDiscountCalculator:
    """Calculate bundle discounts for flight + hotel packages."""

    def __init__(self) -> None:
        """Initialize bundle calculator."""
        self._bundle_discounts: dict[str, float] = {
            "flight_hotel": 0.08,  # 8% off flight+hotel
            "flight_hotel_car": 0.12,  # 12% off all three
        }

    def calculate_package_discount(
        self,
        flight_cost: Decimal,
        hotel_cost: Decimal,
        car_cost: Decimal | None = None,
    ) -> Decimal:
        """
        Calculate bundled package price with discount.

        Args:
            flight_cost: Flight cost
            hotel_cost: Hotel cost
            car_cost: Optional car rental cost

        Returns:
            Discounted total price
        """
        total = flight_cost + hotel_cost
        if car_cost:
            total += car_cost

        # Determine discount tier
        if car_cost:
            discount_rate = self._bundle_discounts["flight_hotel_car"]
        else:
            discount_rate = self._bundle_discounts["flight_hotel"]

        discount = total * Decimal(discount_rate)
        return total - discount

    def get_savings(
        self,
        flight_cost: Decimal,
        hotel_cost: Decimal,
        car_cost: Decimal | None = None,
    ) -> Decimal:
        """
        Calculate savings from bundle discount.

        Args:
            flight_cost: Flight cost
            hotel_cost: Hotel cost
            car_cost: Optional car rental cost

        Returns:
            Savings amount
        """
        total = flight_cost + hotel_cost
        if car_cost:
            total += car_cost

        bundled = self.calculate_package_discount(flight_cost, hotel_cost, car_cost)
        return total - bundled


class FareRuleEngine:
    """Manage fare rules for cancellation and changes."""

    def __init__(self) -> None:
        """Initialize fare rule engine."""
        self._fare_rules: dict[str, dict[str, any]] = {}

    def define_fare_rules(
        self,
        fare_code: str,
        is_refundable: bool,
        change_fee: Decimal,
        cancellation_penalty: Decimal,
    ) -> None:
        """
        Define rules for fare code.

        Args:
            fare_code: Fare code
            is_refundable: Whether refundable
            change_fee: Fee for date/time changes
            cancellation_penalty: Penalty for cancellation
        """
        self._fare_rules[fare_code] = {
            "refundable": is_refundable,
            "change_fee": change_fee,
            "cancellation_penalty": cancellation_penalty,
        }

    def calculate_refund(
        self,
        fare_code: str,
        original_price: Decimal,
        is_cancellation: bool = True,
    ) -> Decimal:
        """
        Calculate refund amount based on fare rules.

        Args:
            fare_code: Fare code
            original_price: Original booking price
            is_cancellation: Whether this is cancellation (vs. change)

        Returns:
            Refund amount
        """
        rules = self._fare_rules.get(fare_code, {})

        if not rules.get("refundable", False):
            return Decimal("0")

        if is_cancellation:
            penalty = rules.get("cancellation_penalty", Decimal("0"))
            return max(Decimal("0"), original_price - penalty)

        change_fee = rules.get("change_fee", Decimal("0"))
        return max(Decimal("0"), original_price - change_fee)

    def get_fare_rules(self, fare_code: str) -> dict[str, any]:
        """
        Get rules for fare code.

        Args:
            fare_code: Fare code

        Returns:
            Fare rules dictionary
        """
        return self._fare_rules.get(fare_code, {})
