"""Flight search and booking module with routing algorithms."""

import heapq
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from thomas.marketplace.travel._exceptions import (
    FlightNotAvailableError,
    InvalidConnectionError,
    InvalidSearchError,
    NoRouteFoundError,
)
from thomas.marketplace.travel._types import (
    FareClass,
    Flight,
)
from thomas.marketplace.travel.geography import AirportDatabase, DistanceCalculator, TimezoneHandler


class FlightGraph:
    """Graph representation of flight network with airports as nodes."""

    def __init__(self, airport_db: AirportDatabase) -> None:
        """
        Initialize flight graph.

        Args:
            airport_db: Airport database instance
        """
        self.airport_db = airport_db
        self._edges: dict[str, list[tuple[str, float]]] = defaultdict(list)
        self._flights: dict[tuple[str, str], list[Flight]] = defaultdict(list)
        self._route_distance: dict[tuple[str, str], float] = {}

    def add_route(self, origin: str, destination: str, distance_km: float) -> None:
        """
        Add route to graph.

        Args:
            origin: Origin airport IATA code
            destination: Destination airport IATA code
            distance_km: Distance in kilometers
        """
        self._edges[origin].append((destination, distance_km))
        self._route_distance[(origin, destination)] = distance_km

    def add_flight(self, flight: Flight) -> None:
        """
        Add flight to graph.

        Args:
            flight: Flight object
        """
        origin = flight.origin.iata_code
        destination = flight.destination.iata_code
        if not self._route_distance.get((origin, destination)):
            distance = DistanceCalculator.distance_between_airports(flight.origin, flight.destination)
            self.add_route(origin, destination, distance)
        self._flights[(origin, destination)].append(flight)

    def get_flights(self, origin: str, destination: str) -> list[Flight]:
        """
        Get all flights between two airports.

        Args:
            origin: Origin airport IATA code
            destination: Destination airport IATA code

        Returns:
            List of Flight objects
        """
        return self._flights.get((origin, destination), [])

    def get_neighbors(self, airport_code: str) -> list[str]:
        """
        Get all airports reachable from given airport.

        Args:
            airport_code: Airport IATA code

        Returns:
            List of destination airport codes
        """
        return [dest for dest, _ in self._edges.get(airport_code, [])]

    def get_distance(self, origin: str, destination: str) -> float | None:
        """
        Get distance between two airports.

        Args:
            origin: Origin airport IATA code
            destination: Destination airport IATA code

        Returns:
            Distance in kilometers, or None if no route
        """
        return self._route_distance.get((origin, destination))


class DijkstraRouter:
    """Dijkstra shortest path algorithm for flight routing."""

    MIN_CONNECTION_TIME_MINUTES = 90
    SAME_TERMINAL_CONNECTION_TIME = 45

    def __init__(self, flight_graph: FlightGraph) -> None:
        """
        Initialize router.

        Args:
            flight_graph: FlightGraph instance
        """
        self.flight_graph = flight_graph

    def find_shortest_path(
        self,
        origin: str,
        destination: str,
        max_stops: int = 2,
    ) -> list[str]:
        """
        Find shortest path between airports using Dijkstra algorithm.

        Args:
            origin: Origin airport IATA code
            destination: Destination airport IATA code
            max_stops: Maximum number of stops

        Returns:
            List of airport codes in order

        Raises:
            NoRouteFoundError: If no path exists
        """
        # Priority queue: (distance, current_airport, path)
        heap: list[tuple[float, str, list[str]]] = [(0, origin, [origin])]
        visited: set[str] = set()
        distances: dict[str, float] = {origin: 0}

        while heap:
            current_distance, current, path = heapq.heappop(heap)

            if current in visited:
                continue

            visited.add(current)

            if current == destination:
                return path

            # Stop if max stops exceeded
            if len(path) - 1 >= max_stops:
                continue

            # Explore neighbors
            for neighbor in self.flight_graph.get_neighbors(current):
                if neighbor in visited:
                    continue

                edge_distance = self.flight_graph.get_distance(current, neighbor) or 0
                new_distance = current_distance + edge_distance

                if new_distance < distances.get(neighbor, float("inf")):
                    distances[neighbor] = new_distance
                    heapq.heappush(heap, (new_distance, neighbor, path + [neighbor]))

        raise NoRouteFoundError(f"No route from {origin} to {destination}")

    @staticmethod
    def validate_connection(
        arrival_time: datetime,
        departure_time: datetime,
        same_terminal: bool = False,
    ) -> bool:
        """
        Validate if connection time is sufficient.

        Args:
            arrival_time: Arrival time at connecting airport
            departure_time: Departure time from connecting airport
            same_terminal: Whether flights are in same terminal

        Returns:
            True if connection is valid

        Raises:
            InvalidConnectionError: If connection time is insufficient
        """
        min_time = (
            DijkstraRouter.SAME_TERMINAL_CONNECTION_TIME
            if same_terminal
            else DijkstraRouter.MIN_CONNECTION_TIME_MINUTES
        )

        connection_minutes = (departure_time - arrival_time).total_seconds() / 60

        if connection_minutes < min_time:
            raise InvalidConnectionError(
                f"Insufficient connection time: {connection_minutes:.0f} minutes " f"(minimum {min_time} required)"
            )

        return True


class FlightScheduler:
    """Flight scheduling with departure/arrival times and timezone handling."""

    def __init__(self, airport_db: AirportDatabase) -> None:
        """
        Initialize flight scheduler.

        Args:
            airport_db: Airport database instance
        """
        self.airport_db = airport_db

    def schedule_flight(
        self,
        flight_number: str,
        airline_code: str,
        origin: str,
        destination: str,
        departure_local: datetime,
        duration_minutes: int,
    ) -> tuple[datetime, datetime]:
        """
        Schedule flight and calculate arrival time with timezone handling.

        Args:
            flight_number: Flight number
            airline_code: Airline IATA code
            origin: Origin airport IATA code
            destination: Destination airport IATA code
            departure_local: Departure time in local timezone
            duration_minutes: Flight duration in minutes

        Returns:
            Tuple of (departure_utc, arrival_local)
        """
        origin_airport = self.airport_db.get_airport(origin)
        dest_airport = self.airport_db.get_airport(destination)

        # Get UTC departure time
        departure_utc = TimezoneHandler.get_utc_time(departure_local, origin_airport.timezone)

        # Calculate arrival time
        arrival_local = TimezoneHandler.calculate_arrival_time(
            departure_local,
            origin_airport.timezone,
            dest_airport.timezone,
            duration_minutes,
        )

        return departure_utc, arrival_local


class FareClassManager:
    """Manage fare classes and availability."""

    def __init__(self) -> None:
        """Initialize fare class manager."""
        self._fare_inventory: dict[str, dict[FareClass, int]] = {}
        self._fare_prices: dict[str, dict[FareClass, Decimal]] = {}

    def set_inventory(
        self,
        flight_id: str,
        fare_class: FareClass,
        available_seats: int,
    ) -> None:
        """
        Set seat inventory for fare class.

        Args:
            flight_id: Flight identifier
            fare_class: Fare class
            available_seats: Number of available seats
        """
        if flight_id not in self._fare_inventory:
            self._fare_inventory[flight_id] = {}

        self._fare_inventory[flight_id][fare_class] = available_seats

    def get_availability(self, flight_id: str, fare_class: FareClass) -> int:
        """
        Get available seats for fare class.

        Args:
            flight_id: Flight identifier
            fare_class: Fare class

        Returns:
            Number of available seats
        """
        return self._fare_inventory.get(flight_id, {}).get(fare_class, 0)

    def reserve_seat(self, flight_id: str, fare_class: FareClass) -> bool:
        """
        Reserve seat in fare class.

        Args:
            flight_id: Flight identifier
            fare_class: Fare class

        Returns:
            True if reservation successful

        Raises:
            FlightNotAvailableError: If no seats available
        """
        available = self.get_availability(flight_id, fare_class)
        if available <= 0:
            raise FlightNotAvailableError(f"No {fare_class.value} seats available on {flight_id}")

        self._fare_inventory[flight_id][fare_class] = available - 1
        return True

    def set_price(
        self,
        flight_id: str,
        fare_class: FareClass,
        price: Decimal,
    ) -> None:
        """
        Set price for fare class.

        Args:
            flight_id: Flight identifier
            fare_class: Fare class
            price: Price in currency
        """
        if flight_id not in self._fare_prices:
            self._fare_prices[flight_id] = {}

        self._fare_prices[flight_id][fare_class] = price

    def get_price(self, flight_id: str, fare_class: FareClass) -> Decimal | None:
        """
        Get price for fare class.

        Args:
            flight_id: Flight identifier
            fare_class: Fare class

        Returns:
            Price, or None if not set
        """
        return self._fare_prices.get(flight_id, {}).get(fare_class)


class CodeshareManager:
    """Handle codeshare flights and operating carriers."""

    def __init__(self) -> None:
        """Initialize codeshare manager."""
        self._codeshares: dict[str, list[str]] = {}

    def add_codeshare(self, marketing_flight: str, operating_flights: list[str]) -> None:
        """
        Register codeshare relationship.

        Args:
            marketing_flight: Marketing flight number
            operating_flights: List of operating flight numbers
        """
        self._codeshares[marketing_flight] = operating_flights

    def get_operating_flights(self, marketing_flight: str) -> list[str]:
        """
        Get operating flights for codeshare.

        Args:
            marketing_flight: Marketing flight number

        Returns:
            List of operating flight numbers
        """
        return self._codeshares.get(marketing_flight, [])

    def is_codeshare(self, flight_number: str) -> bool:
        """
        Check if flight is codeshare.

        Args:
            flight_number: Flight number

        Returns:
            True if flight is codeshare
        """
        return flight_number in self._codeshares


class FlightSearchEngine:
    """Main flight search engine combining all components."""

    def __init__(self, airport_db: AirportDatabase) -> None:
        """
        Initialize search engine.

        Args:
            airport_db: Airport database instance
        """
        self.airport_db = airport_db
        self.graph = FlightGraph(airport_db)
        self.router = DijkstraRouter(self.graph)
        self.scheduler = FlightScheduler(airport_db)
        self.fare_manager = FareClassManager()
        self.codeshare_manager = CodeshareManager()
        self._flights: list[Flight] = []

    def add_flight(self, flight: Flight) -> None:
        """
        Add flight to searchable inventory.

        Args:
            flight: Flight object
        """
        self._flights.append(flight)
        self.graph.add_flight(flight)

    def search_direct_flights(
        self,
        origin: str,
        destination: str,
        departure_date: datetime,
        fare_class: FareClass = FareClass.ECONOMY,
    ) -> list[Flight]:
        """
        Search for direct flights.

        Args:
            origin: Origin airport IATA code
            destination: Destination airport IATA code
            departure_date: Departure date
            fare_class: Desired fare class

        Returns:
            List of matching Flight objects

        Raises:
            InvalidSearchError: If search parameters invalid
        """
        if not origin or not destination:
            raise InvalidSearchError("Origin and destination required")

        if origin == destination:
            raise InvalidSearchError("Origin and destination must differ")

        # Validate airports exist
        self.airport_db.get_airport(origin)
        self.airport_db.get_airport(destination)

        flights = self.graph.get_flights(origin, destination)
        results = []

        for flight in flights:
            if flight.departure_time.date() == departure_date.date() and not flight.is_cancelled and flight.stops == 0:
                # Check availability
                if self.fare_manager.get_availability(flight.flight_number, fare_class) > 0:
                    results.append(flight)

        return sorted(results, key=lambda f: f.departure_time)

    def search_multi_city(
        self,
        segments: list[tuple[str, str, datetime]],
        fare_class: FareClass = FareClass.ECONOMY,
    ) -> list[list[Flight]]:
        """
        Search for multi-city itineraries.

        Args:
            segments: List of (origin, destination, departure_date) tuples
            fare_class: Desired fare class

        Returns:
            List of possible itineraries, each a list of flights

        Raises:
            InvalidSearchError: If search parameters invalid
        """
        if not segments:
            raise InvalidSearchError("At least one segment required")

        itineraries = []
        current_options = []

        # Search first segment
        for origin, destination, departure_date in segments:
            flights = self.search_direct_flights(origin, destination, departure_date, fare_class)
            if not flights:
                # Try connecting flights
                try:
                    path = self.router.find_shortest_path(origin, destination)
                    flights = self._find_connecting_flights(path, departure_date, fare_class)
                except NoRouteFoundError:
                    continue

            if not current_options:
                current_options = [[f] for f in flights]
            else:
                new_options = []
                for option in current_options:
                    for flight in flights:
                        new_options.append(option + [flight])
                current_options = new_options

        return current_options

    def _find_connecting_flights(
        self,
        airports: list[str],
        departure_date: datetime,
        fare_class: FareClass,
    ) -> list[Flight]:
        """
        Find connecting flights for given airport sequence.

        Args:
            airports: List of airport codes in sequence
            departure_date: Departure date
            fare_class: Desired fare class

        Returns:
            List of connecting Flight objects

        Raises:
            NoRouteFoundError: If valid connections not found
        """
        connections = []

        for i in range(len(airports) - 1):
            origin = airports[i]
            destination = airports[i + 1]
            flights = self.search_direct_flights(origin, destination, departure_date, fare_class)

            if not flights:
                raise NoRouteFoundError(f"No flights from {origin} to {destination}")

            connections.append(flights[0])

        return connections

    def calculate_route_statistics(
        self,
        origin: str,
        destination: str,
    ) -> dict[str, any]:
        """
        Calculate statistics for route.

        Args:
            origin: Origin airport IATA code
            destination: Destination airport IATA code

        Returns:
            Dictionary with route statistics
        """
        flights = self.graph.get_flights(origin, destination)

        if not flights:
            return {"flights": 0, "average_price": None, "load_factor": None}

        total_price = sum(sum(fare.base_price for fare in f.fares.values()) for f in flights)

        total_capacity = sum(len(f.seats) for f in flights)
        occupied = sum(len([s for s in f.seats.values() if not s.is_available]) for f in flights)

        return {
            "flights": len(flights),
            "average_price": Decimal(total_price) / len(flights) if flights else None,
            "load_factor": occupied / total_capacity if total_capacity > 0 else 0,
        }
