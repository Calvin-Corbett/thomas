"""Tests for flight search and booking module."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from thomas.travel._exceptions import FlightNotAvailableError, InvalidConnectionError, NoRouteFoundError
from thomas.travel._types import Currency, Fare, FareClass, Flight, Seat
from thomas.travel.flights import (
    CodeshareManager,
    DijkstraRouter,
    FareClassManager,
    FlightGraph,
    FlightScheduler,
    FlightSearchEngine,
)
from thomas.travel.geography import AirportDatabase


@pytest.fixture
def airport_db():
    """Create airport database."""
    return AirportDatabase()


@pytest.fixture
def flight_graph(airport_db):
    """Create flight graph."""
    return FlightGraph(airport_db)


@pytest.fixture
def sample_airports(airport_db):
    """Get sample airports."""
    return {
        "jfk": airport_db.get_airport("JFK"),
        "lax": airport_db.get_airport("LAX"),
        "ord": airport_db.get_airport("ORD"),
    }


@pytest.fixture
def sample_flight(sample_airports):
    """Create sample flight."""
    return Flight(
        flight_number="AA100",
        airline_code="AA",
        aircraft_type="Boeing 777",
        origin=sample_airports["jfk"],
        destination=sample_airports["lax"],
        departure_time=datetime.now() + timedelta(days=7),
        arrival_time=datetime.now() + timedelta(days=7, hours=5),
        duration_minutes=300,
        stops=0,
        fares={
            FareClass.ECONOMY: Fare(
                base_price=Decimal("250"),
                taxes=Decimal("50"),
                fees=Decimal("10"),
                currency=Currency.USD,
                fare_class=FareClass.ECONOMY,
                availability_count=100,
            )
        },
        seats={
            "1A": Seat("1A", 1, "A", FareClass.ECONOMY),
            "1B": Seat("1B", 1, "B", FareClass.ECONOMY),
        },
    )


class TestFlightGraph:
    """Test flight graph operations."""

    def test_add_route(self, flight_graph):
        """Test adding route to graph."""
        flight_graph.add_route("JFK", "LAX", 2451.0)
        neighbors = flight_graph.get_neighbors("JFK")
        assert "LAX" in neighbors

    def test_add_flight(self, flight_graph, sample_flight):
        """Test adding flight to graph."""
        flight_graph.add_flight(sample_flight)
        flights = flight_graph.get_flights("JFK", "LAX")
        assert len(flights) == 1
        assert flights[0].flight_number == "AA100"

    def test_get_distance(self, flight_graph):
        """Test getting distance between airports."""
        flight_graph.add_route("JFK", "LAX", 2451.0)
        distance = flight_graph.get_distance("JFK", "LAX")
        assert distance == 2451.0

    def test_get_nonexistent_distance(self, flight_graph):
        """Test getting distance for non-existent route."""
        distance = flight_graph.get_distance("JFK", "SFO")
        assert distance is None


class TestDijkstraRouter:
    """Test Dijkstra shortest path algorithm."""

    def test_find_shortest_path_direct(self, flight_graph):
        """Test finding direct path."""
        flight_graph.add_route("JFK", "LAX", 2451.0)
        router = DijkstraRouter(flight_graph)
        path = router.find_shortest_path("JFK", "LAX")
        assert path == ["JFK", "LAX"]

    def test_find_shortest_path_with_connections(self, flight_graph):
        """Test finding path with connections."""
        flight_graph.add_route("JFK", "ORD", 790.0)
        flight_graph.add_route("ORD", "LAX", 2015.0)
        flight_graph.add_route("JFK", "LAX", 2451.0)

        router = DijkstraRouter(flight_graph)
        path = router.find_shortest_path("JFK", "LAX", max_stops=2)
        assert len(path) >= 2

    def test_no_route_found(self, flight_graph):
        """Test error when no route exists."""
        router = DijkstraRouter(flight_graph)
        with pytest.raises(NoRouteFoundError):
            router.find_shortest_path("JFK", "SFO")

    def test_validate_connection_valid(self):
        """Test validating sufficient connection time."""
        arrival = datetime.now()
        departure = arrival + timedelta(minutes=120)
        assert DijkstraRouter.validate_connection(arrival, departure)

    def test_validate_connection_insufficient(self):
        """Test error with insufficient connection time."""
        arrival = datetime.now()
        departure = arrival + timedelta(minutes=30)
        with pytest.raises(InvalidConnectionError):
            DijkstraRouter.validate_connection(arrival, departure)


class TestFlightScheduler:
    """Test flight scheduling."""

    def test_schedule_flight(self, airport_db):
        """Test scheduling flight with timezone handling."""
        scheduler = FlightScheduler(airport_db)
        departure_local = datetime.now()

        departure_utc, arrival_local = scheduler.schedule_flight("AA100", "AA", "JFK", "LAX", departure_local, 300)

        assert departure_utc is not None
        assert arrival_local is not None
        assert (arrival_local - departure_local).total_seconds() / 60 > 300


class TestFareClassManager:
    """Test fare class management."""

    def test_set_inventory(self):
        """Test setting seat inventory."""
        manager = FareClassManager()
        manager.set_inventory("AA100", FareClass.ECONOMY, 100)
        assert manager.get_availability("AA100", FareClass.ECONOMY) == 100

    def test_reserve_seat(self):
        """Test reserving seat."""
        manager = FareClassManager()
        manager.set_inventory("AA100", FareClass.ECONOMY, 100)
        manager.reserve_seat("AA100", FareClass.ECONOMY)
        assert manager.get_availability("AA100", FareClass.ECONOMY) == 99

    def test_reserve_seat_unavailable(self):
        """Test error when reserving unavailable seat."""
        manager = FareClassManager()
        manager.set_inventory("AA100", FareClass.ECONOMY, 0)
        with pytest.raises(FlightNotAvailableError):
            manager.reserve_seat("AA100", FareClass.ECONOMY)

    def test_set_price(self):
        """Test setting fare price."""
        manager = FareClassManager()
        manager.set_price("AA100", FareClass.ECONOMY, Decimal("250"))
        assert manager.get_price("AA100", FareClass.ECONOMY) == Decimal("250")


class TestCodeshareManager:
    """Test codeshare handling."""

    def test_add_codeshare(self):
        """Test adding codeshare relationship."""
        manager = CodeshareManager()
        manager.add_codeshare("BA100", ["AA100", "UA100"])
        assert manager.is_codeshare("BA100")
        assert "AA100" in manager.get_operating_flights("BA100")


class TestFlightSearchEngine:
    """Test flight search engine."""

    def test_search_direct_flights(self, airport_db, sample_flight):
        """Test searching direct flights."""
        engine = FlightSearchEngine(airport_db)
        engine.add_flight(sample_flight)
        engine.fare_manager.set_inventory("AA100", FareClass.ECONOMY, 100)

        results = engine.search_direct_flights("JFK", "LAX", sample_flight.departure_time)

        assert len(results) > 0
        assert results[0].flight_number == "AA100"

    def test_search_invalid_route(self, airport_db):
        """Test error with invalid search parameters."""
        engine = FlightSearchEngine(airport_db)
        with pytest.raises(Exception):
            engine.search_direct_flights("JFK", "JFK", datetime.now())

    def test_calculate_route_statistics(self, airport_db, sample_flight):
        """Test calculating route statistics."""
        engine = FlightSearchEngine(airport_db)
        engine.add_flight(sample_flight)
        engine.fare_manager.set_inventory("AA100", FareClass.ECONOMY, 100)

        stats = engine.calculate_route_statistics("JFK", "LAX")

        assert stats["flights"] > 0
        assert stats["average_price"] is not None


class TestFlightIntegration:
    """Integration tests for flight operations."""

    def test_end_to_end_booking(self, airport_db, sample_flight):
        """Test complete flight booking process."""
        engine = FlightSearchEngine(airport_db)
        engine.add_flight(sample_flight)
        engine.fare_manager.set_inventory("AA100", FareClass.ECONOMY, 100)

        # Search
        flights = engine.search_direct_flights("JFK", "LAX", sample_flight.departure_time)
        assert len(flights) > 0

        # Reserve seat
        engine.fare_manager.reserve_seat("AA100", FareClass.ECONOMY)
        assert engine.fare_manager.get_availability("AA100", FareClass.ECONOMY) == 99

    def test_multi_city_routing(self, airport_db):
        """Test multi-city route planning."""
        engine = FlightSearchEngine(airport_db)
        engine.graph.add_route("JFK", "ORD", 790.0)
        engine.graph.add_route("ORD", "LAX", 2015.0)

        path = engine.router.find_shortest_path("JFK", "LAX")
        assert len(path) >= 2
