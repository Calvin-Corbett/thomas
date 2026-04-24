"""Travel analytics engine for insights and reporting."""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from thomas.marketplace.travel._types import Booking, Flight


class BookingTrendAnalyzer:
    """Analyze booking trends and patterns."""

    def __init__(self) -> None:
        """Initialize trend analyzer."""
        self._bookings: list[Booking] = []

    def record_booking(self, booking: Booking) -> None:
        """
        Record booking for analysis.

        Args:
            booking: Booking to record
        """
        self._bookings.append(booking)

    def get_bookings_by_route(self, origin: str, destination: str) -> list[Booking]:
        """
        Get bookings for specific route.

        Args:
            origin: Origin airport code
            destination: Destination airport code

        Returns:
            List of bookings
        """
        return [
            b
            for b in self._bookings
            if b.flight.origin.iata_code == origin and b.flight.destination.iata_code == destination
        ]

    def get_bookings_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[Booking]:
        """
        Get bookings in date range.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of bookings
        """
        return [b for b in self._bookings if start_date <= b.booking_date <= end_date]

    def analyze_trend(
        self,
        origin: str,
        destination: str,
    ) -> dict[str, any]:
        """
        Analyze booking trends for route.

        Args:
            origin: Origin airport code
            destination: Destination airport code

        Returns:
            Trend analysis
        """
        bookings = self.get_bookings_by_route(origin, destination)

        if not bookings:
            return {"route": f"{origin}-{destination}", "bookings": 0}

        # Group by date
        bookings_by_date: dict[date, int] = defaultdict(int)
        total_revenue = Decimal("0")

        for booking in bookings:
            date_key = booking.booking_date.date()
            bookings_by_date[date_key] += 1
            total_revenue += booking.price

        average_price = total_revenue / len(bookings) if bookings else Decimal("0")

        return {
            "route": f"{origin}-{destination}",
            "bookings": len(bookings),
            "total_revenue": total_revenue,
            "average_price": average_price,
            "bookings_by_date": dict(bookings_by_date),
        }


class RevenueAnalytics:
    """Analyze revenue metrics."""

    def __init__(self) -> None:
        """Initialize revenue analyzer."""
        self._flights: list[Flight] = []
        self._bookings: list[Booking] = []

    def record_flight(self, flight: Flight) -> None:
        """
        Record flight for analysis.

        Args:
            flight: Flight to record
        """
        self._flights.append(flight)

    def record_booking(self, booking: Booking) -> None:
        """
        Record booking for analysis.

        Args:
            booking: Booking to record
        """
        self._bookings.append(booking)

    def calculate_yield_per_passenger_mile(
        self,
        origin: str,
        destination: str,
    ) -> Decimal | None:
        """
        Calculate yield per passenger-mile (RPM).

        Args:
            origin: Origin airport code
            destination: Destination airport code

        Returns:
            Yield per passenger-mile, or None
        """
        bookings = [
            b
            for b in self._bookings
            if b.flight.origin.iata_code == origin and b.flight.destination.iata_code == destination
        ]

        if not bookings:
            return None

        total_revenue = sum(b.price for b in bookings)
        total_passengers = sum(b.total_passengers() for b in bookings)

        # Find distance from flight
        flight = next(
            (f for f in self._flights if f.origin.iata_code == origin and f.destination.iata_code == destination), None
        )

        if not flight:
            return None

        total_passenger_miles = total_passengers * flight.origin.latitude  # Simplified

        if total_passenger_miles == 0:
            return None

        return total_revenue / Decimal(total_passenger_miles)

    def calculate_route_revenue(
        self,
        origin: str,
        destination: str,
    ) -> Decimal:
        """
        Calculate total revenue for route.

        Args:
            origin: Origin airport code
            destination: Destination airport code

        Returns:
            Total revenue
        """
        bookings = [
            b
            for b in self._bookings
            if b.flight.origin.iata_code == origin and b.flight.destination.iata_code == destination
        ]

        return sum(b.price for b in bookings)


class RoutePerformanceAnalyzer:
    """Analyze flight route performance metrics."""

    def __init__(self) -> None:
        """Initialize route analyzer."""
        self._flights: list[Flight] = []
        self._bookings: list[Booking] = []

    def record_flight(self, flight: Flight) -> None:
        """Record flight."""
        self._flights.append(flight)

    def record_booking(self, booking: Booking) -> None:
        """Record booking."""
        self._bookings.append(booking)

    def calculate_load_factor(
        self,
        origin: str,
        destination: str,
    ) -> float:
        """
        Calculate load factor (percentage of seats filled).

        Args:
            origin: Origin airport code
            destination: Destination airport code

        Returns:
            Load factor (0.0-1.0)
        """
        bookings = [
            b
            for b in self._bookings
            if b.flight.origin.iata_code == origin and b.flight.destination.iata_code == destination
        ]

        flight = next(
            (f for f in self._flights if f.origin.iata_code == origin and f.destination.iata_code == destination), None
        )

        if not flight or not bookings:
            return 0.0

        total_capacity = len(flight.seats)
        total_booked = sum(b.total_passengers() for b in bookings)

        return min(1.0, total_booked / total_capacity) if total_capacity > 0 else 0.0

    def calculate_revenue_per_available_seat_mile(
        self,
        origin: str,
        destination: str,
    ) -> Decimal | None:
        """
        Calculate RASM (Revenue per Available Seat Mile).

        Args:
            origin: Origin airport code
            destination: Destination airport code

        Returns:
            RASM, or None
        """
        bookings = [
            b
            for b in self._bookings
            if b.flight.origin.iata_code == origin and b.flight.destination.iata_code == destination
        ]

        flight = next(
            (f for f in self._flights if f.origin.iata_code == origin and f.destination.iata_code == destination), None
        )

        if not flight or not bookings:
            return None

        total_revenue = sum(b.price for b in bookings)
        capacity_miles = len(flight.seats) * flight.duration_minutes / 60  # Simplified

        if capacity_miles == 0:
            return None

        return total_revenue / Decimal(capacity_miles)

    def analyze_route(
        self,
        origin: str,
        destination: str,
    ) -> dict[str, any]:
        """
        Comprehensive route analysis.

        Args:
            origin: Origin airport code
            destination: Destination airport code

        Returns:
            Route analysis
        """
        return {
            "route": f"{origin}-{destination}",
            "load_factor": self.calculate_load_factor(origin, destination),
            "rasm": self.calculate_revenue_per_available_seat_mile(origin, destination),
            "bookings": len(
                [
                    b
                    for b in self._bookings
                    if b.flight.origin.iata_code == origin and b.flight.destination.iata_code == destination
                ]
            ),
        }


class CustomerSegmentation:
    """Segment customers by travel patterns."""

    def __init__(self) -> None:
        """Initialize segmentation."""
        self._bookings: list[Booking] = []

    def record_booking(self, booking: Booking) -> None:
        """Record booking."""
        self._bookings.append(booking)

    def segment_by_type(self) -> dict[str, list[Booking]]:
        """
        Segment customers by trip type (business vs leisure).

        Returns:
            Segmented bookings
        """
        business = []
        leisure = []

        for booking in self._bookings:
            # Heuristic: weekday departures before 9am = business
            if booking.flight.departure_time.weekday() < 5 and booking.flight.departure_time.hour < 9:
                business.append(booking)
            else:
                leisure.append(booking)

        return {
            "business": business,
            "leisure": leisure,
        }

    def segment_by_frequency(self) -> dict[str, list[str]]:
        """
        Segment customers by booking frequency.

        Returns:
            Frequent vs occasional travelers
        """
        customer_bookings: dict[str, list[Booking]] = defaultdict(list)

        for booking in self._bookings:
            # Use first passenger as identifier
            if booking.passengers:
                customer_id = booking.passengers[0].full_name
                customer_bookings[customer_id].append(booking)

        frequent = {}
        occasional = {}

        for customer, bookings in customer_bookings.items():
            if len(bookings) >= 5:
                frequent[customer] = bookings
            else:
                occasional[customer] = bookings

        return {
            "frequent": list(frequent.keys()),
            "occasional": list(occasional.keys()),
        }


class SeasonalDemandAnalyzer:
    """Analyze seasonal demand patterns."""

    def __init__(self) -> None:
        """Initialize seasonal analyzer."""
        self._demand_by_month: dict[int, float] = {}
        self._demand_by_day_of_week: dict[int, float] = {}

    def record_demand(
        self,
        booking_date: datetime,
        demand_level: float,
    ) -> None:
        """
        Record demand observation.

        Args:
            booking_date: Booking date
            demand_level: Demand level (0.0-1.0)
        """
        month = booking_date.month
        day_of_week = booking_date.weekday()

        if month not in self._demand_by_month:
            self._demand_by_month[month] = 0.0

        if day_of_week not in self._demand_by_day_of_week:
            self._demand_by_day_of_week[day_of_week] = 0.0

        # Running average
        self._demand_by_month[month] = self._demand_by_month[month] * 0.7 + demand_level * 0.3
        self._demand_by_day_of_week[day_of_week] = self._demand_by_day_of_week[day_of_week] * 0.7 + demand_level * 0.3

    def get_seasonal_index(self, month: int) -> float:
        """
        Get seasonal demand index for month.

        Args:
            month: Month (1-12)

        Returns:
            Seasonal index (1.0 = average)
        """
        if not self._demand_by_month:
            return 1.0

        avg_demand = sum(self._demand_by_month.values()) / len(self._demand_by_month)
        return self._demand_by_month.get(month, avg_demand) / avg_demand if avg_demand > 0 else 1.0

    def get_peak_seasons(self) -> list[tuple[int, float]]:
        """
        Get peak seasons ranked.

        Returns:
            List of (month, demand) tuples sorted by demand
        """
        return sorted(self._demand_by_month.items(), key=lambda x: x[1], reverse=True)


class CancellationAnalytics:
    """Analyze cancellation patterns."""

    def __init__(self) -> None:
        """Initialize cancellation analyzer."""
        self._cancellations: list[dict] = []
        self._total_bookings = 0

    def record_booking(self) -> None:
        """Record booking."""
        self._total_bookings += 1

    def record_cancellation(
        self,
        booking_id: str,
        days_before_departure: int,
        reason: str | None = None,
    ) -> None:
        """
        Record cancellation.

        Args:
            booking_id: Booking identifier
            days_before_departure: Days before departure when cancelled
            reason: Cancellation reason
        """
        self._cancellations.append(
            {
                "booking_id": booking_id,
                "days_before": days_before_departure,
                "reason": reason,
                "timestamp": datetime.utcnow(),
            }
        )

    def get_cancellation_rate(self) -> float:
        """
        Get overall cancellation rate.

        Returns:
            Cancellation rate (0.0-1.0)
        """
        if self._total_bookings == 0:
            return 0.0
        return len(self._cancellations) / self._total_bookings

    def analyze_cancellation_timing(self) -> dict[str, int]:
        """
        Analyze when cancellations occur.

        Returns:
            Counts by timing window
        """
        timing = {
            "more_than_30_days": 0,
            "14_to_30_days": 0,
            "7_to_14_days": 0,
            "3_to_7_days": 0,
            "less_than_3_days": 0,
        }

        for cancellation in self._cancellations:
            days = cancellation["days_before"]
            if days > 30:
                timing["more_than_30_days"] += 1
            elif days > 14:
                timing["14_to_30_days"] += 1
            elif days > 7:
                timing["7_to_14_days"] += 1
            elif days > 3:
                timing["3_to_7_days"] += 1
            else:
                timing["less_than_3_days"] += 1

        return timing


class RouteMarketAnalysis:
    """Analyze market pricing on routes."""

    def __init__(self) -> None:
        """Initialize route market analyzer."""
        self._market_prices: dict[str, dict[str, Decimal]] = {}

    def record_market_price(
        self,
        route: str,
        airline: str,
        price: Decimal,
    ) -> None:
        """
        Record market price.

        Args:
            route: Route code
            airline: Airline name
            price: Price
        """
        if route not in self._market_prices:
            self._market_prices[route] = {}

        self._market_prices[route][airline] = price

    def get_market_position(
        self,
        route: str,
        our_price: Decimal,
    ) -> dict[str, any]:
        """
        Analyze market position.

        Args:
            route: Route code
            our_price: Our price

        Returns:
            Market analysis
        """
        market_prices_by_airline = self._market_prices.get(route, {})

        if not market_prices_by_airline:
            return {"route": route, "market_price_count": 0}

        market_prices = list(market_prices_by_airline.values())
        avg_market_price = sum(market_prices) / len(market_prices)
        min_price = min(market_prices)
        max_price = max(market_prices)

        price_position = (our_price - min_price) / (max_price - min_price) if max_price > min_price else 0.5

        return {
            "route": route,
            "our_price": our_price,
            "market_price_count": len(market_prices_by_airline),
            "average_market_price": avg_market_price,
            "min_market_price": min_price,
            "max_market_price": max_price,
            "price_position": price_position,  # 0.0 = cheapest, 1.0 = most expensive
        }
