"""Tests for itinerary management module."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from thomas.travel._exceptions import BookingError
from thomas.travel._types import Activity, Airport, Currency, Flight, Itinerary, Trip
from thomas.travel.itinerary import (
    BudgetTracker,
    ConflictDetector,
    DayPlanner,
    ItineraryOptimizer,
    ItinerarySharing,
    ItineraryVersioning,
    MultiSegmentAssembler,
)


@pytest.fixture
def sample_trip():
    """Create sample trip."""
    return Trip(
        trip_id="TRIP001",
        start_date=datetime.now() + timedelta(days=7),
        end_date=datetime.now() + timedelta(days=14),
        origin_city="New York",
        destination_cities=["Los Angeles"],
        budget=Decimal("5000"),
        currency=Currency.USD,
        passengers=[],
        trip_type="round_trip",
    )


@pytest.fixture
def sample_airports():
    """Create sample airports."""
    return {
        "jfk": Airport(
            iata_code="JFK",
            icao_code="KJFK",
            name="John F. Kennedy",
            city="New York",
            country="USA",
            latitude=40.6413,
            longitude=-73.7781,
            timezone="America/New_York",
            altitude_feet=13,
        ),
        "lax": Airport(
            iata_code="LAX",
            icao_code="KLAX",
            name="Los Angeles",
            city="Los Angeles",
            country="USA",
            latitude=33.9425,
            longitude=-118.4081,
            timezone="America/Los_Angeles",
            altitude_feet=126,
        ),
    }


@pytest.fixture
def sample_flights(sample_airports):
    """Create sample flights."""
    start_time = datetime.now() + timedelta(days=7)
    return [
        Flight(
            flight_number="AA100",
            airline_code="AA",
            aircraft_type="Boeing 777",
            origin=sample_airports["jfk"],
            destination=sample_airports["lax"],
            departure_time=start_time,
            arrival_time=start_time + timedelta(hours=5),
            duration_minutes=300,
        ),
        Flight(
            flight_number="AA101",
            airline_code="AA",
            aircraft_type="Boeing 777",
            origin=sample_airports["lax"],
            destination=sample_airports["jfk"],
            departure_time=start_time + timedelta(days=7),
            arrival_time=start_time + timedelta(days=7, hours=5),
            duration_minutes=300,
        ),
    ]


@pytest.fixture
def sample_activities():
    """Create sample activities."""
    start_time = datetime.now() + timedelta(days=8)
    return [
        Activity(
            name="City Tour",
            location="Los Angeles",
            start_time=start_time,
            end_time=start_time + timedelta(hours=3),
            category="sightseeing",
            price=Decimal("50"),
            currency=Currency.USD,
            duration_minutes=180,
            participants=2,
            provider="LocalTours",
        ),
        Activity(
            name="Beach Day",
            location="Los Angeles",
            start_time=start_time + timedelta(days=1),
            end_time=start_time + timedelta(days=1, hours=4),
            category="recreation",
            price=Decimal("0"),
            currency=Currency.USD,
            duration_minutes=240,
            participants=2,
            provider="Self",
        ),
    ]


class TestMultiSegmentAssembler:
    """Test multi-segment trip assembly."""

    def test_assemble_trip(self, sample_trip, sample_flights, sample_activities):
        """Test assembling complete itinerary."""
        assembler = MultiSegmentAssembler()

        itinerary = assembler.assemble_trip(
            sample_trip,
            sample_flights,
            [],
            sample_activities,
        )

        assert itinerary.trip == sample_trip
        assert len(itinerary.flights) == 2
        assert len(itinerary.activities) == 2

    def test_get_itinerary(self, sample_trip, sample_flights):
        """Test retrieving itinerary."""
        assembler = MultiSegmentAssembler()
        itinerary = assembler.assemble_trip(sample_trip, sample_flights, [], [])

        retrieved = assembler.get_itinerary(itinerary.itinerary_id)
        assert retrieved is not None
        assert retrieved.trip_id == sample_trip.trip_id


class TestItineraryOptimizer:
    """Test itinerary optimization."""

    def test_minimize_wait_times(self, sample_trip, sample_activities):
        """Test optimizing activities to minimize wait times."""
        itinerary = Itinerary(
            itinerary_id="IT001",
            trip=sample_trip,
            activities=sample_activities,
        )

        optimizer = ItineraryOptimizer()
        optimized = optimizer.minimize_wait_times(itinerary)

        # Activities should be sorted by time
        for i in range(len(optimized.activities) - 1):
            assert optimized.activities[i].start_time <= optimized.activities[i + 1].start_time

    def test_group_by_location(self, sample_trip, sample_activities):
        """Test grouping activities by location."""
        itinerary = Itinerary(
            itinerary_id="IT001",
            trip=sample_trip,
            activities=sample_activities,
        )

        optimizer = ItineraryOptimizer()
        grouped = optimizer.group_by_location(itinerary)

        assert "Los Angeles" in grouped
        assert len(grouped["Los Angeles"]) == 2


class TestDayPlanner:
    """Test daily activity planning."""

    def test_plan_day(self, sample_activities):
        """Test planning activities for a day."""
        planner = DayPlanner()
        plan = planner.plan_day(date.today() + timedelta(days=8), sample_activities[:1])

        assert len(plan["activities"]) > 0
        assert plan["total_time"].total_seconds() > 0

    def test_get_daily_schedule(self, sample_activities):
        """Test retrieving daily schedule."""
        planner = DayPlanner()
        test_date = date.today() + timedelta(days=8)

        planner.plan_day(test_date, sample_activities[:1])
        schedule = planner.get_daily_schedule(test_date)

        assert len(schedule) > 0

    def test_suggest_activities(self, sample_activities):
        """Test suggesting activities that fit available time."""
        planner = DayPlanner()
        available_time = timedelta(hours=2)

        suggestions = planner.suggest_activities(available_time, sample_activities)

        total_duration = sum(a.duration_minutes for a in suggestions)
        assert total_duration * 60 <= available_time.total_seconds() * 1.1  # Allow 10% buffer


class TestItinerarySharing:
    """Test itinerary sharing."""

    def test_share_itinerary(self, sample_trip, sample_flights):
        """Test sharing itinerary."""
        assembler = MultiSegmentAssembler()
        itinerary = assembler.assemble_trip(sample_trip, sample_flights, [], [])

        sharer = ItinerarySharing()
        emails = ["jane@example.com", "john@example.com"]

        result = sharer.share_itinerary(itinerary.itinerary_id, emails)

        assert result["itinerary_id"] == itinerary.itinerary_id
        assert len(result["shared_with"]) == 2

    def test_get_shared_users(self, sample_trip, sample_flights):
        """Test retrieving shared users list."""
        assembler = MultiSegmentAssembler()
        itinerary = assembler.assemble_trip(sample_trip, sample_flights, [], [])

        sharer = ItinerarySharing()
        emails = ["jane@example.com"]
        sharer.share_itinerary(itinerary.itinerary_id, emails)

        shared = sharer.get_shared_users(itinerary.itinerary_id)
        assert "jane@example.com" in shared

    def test_generate_share_link(self, sample_trip, sample_flights):
        """Test generating shareable link."""
        assembler = MultiSegmentAssembler()
        itinerary = assembler.assemble_trip(sample_trip, sample_flights, [], [])

        sharer = ItinerarySharing()
        link = sharer.generate_share_link(itinerary.itinerary_id)

        assert "itinerary.travel/share/" in link


class TestItineraryVersioning:
    """Test itinerary versioning."""

    def test_create_version(self, sample_trip, sample_flights):
        """Test creating itinerary version."""
        assembler = MultiSegmentAssembler()
        itinerary = assembler.assemble_trip(sample_trip, sample_flights, [], [])

        versioner = ItineraryVersioning()
        version = versioner.create_version(itinerary.itinerary_id, itinerary, "Initial version")

        assert version["version"] == 1
        assert version["flights_count"] == 2

    def test_get_versions(self, sample_trip, sample_flights):
        """Test retrieving version history."""
        assembler = MultiSegmentAssembler()
        itinerary = assembler.assemble_trip(sample_trip, sample_flights, [], [])

        versioner = ItineraryVersioning()
        versioner.create_version(itinerary.itinerary_id, itinerary, "V1")
        versioner.create_version(itinerary.itinerary_id, itinerary, "V2")

        versions = versioner.get_versions(itinerary.itinerary_id)
        assert len(versions) == 2


class TestConflictDetector:
    """Test conflict detection."""

    def test_no_conflicts(self, sample_trip, sample_flights, sample_activities):
        """Test detecting no conflicts when activities don't overlap."""
        itinerary = Itinerary(
            itinerary_id="IT001",
            trip=sample_trip,
            flights=sample_flights,
            activities=sample_activities,
        )

        detector = ConflictDetector()
        has_conflicts, conflicts = detector.check_conflicts(itinerary)

        # Activities are on different days, should not conflict
        assert not has_conflicts or len(conflicts) == 0

    def test_detect_overlapping_activities(self, sample_trip):
        """Test detecting overlapping activities."""
        start_time = datetime.now() + timedelta(days=8)

        activities = [
            Activity(
                name="Activity 1",
                location="LA",
                start_time=start_time,
                end_time=start_time + timedelta(hours=2),
                category="test",
                price=Decimal("0"),
                currency=Currency.USD,
                duration_minutes=120,
                participants=1,
                provider="Test",
            ),
            Activity(
                name="Activity 2",
                location="LA",
                start_time=start_time + timedelta(hours=1),  # Overlaps
                end_time=start_time + timedelta(hours=3),
                category="test",
                price=Decimal("0"),
                currency=Currency.USD,
                duration_minutes=120,
                participants=1,
                provider="Test",
            ),
        ]

        itinerary = Itinerary(
            itinerary_id="IT001",
            trip=sample_trip,
            activities=activities,
        )

        detector = ConflictDetector()
        has_conflicts, conflicts = detector.check_conflicts(itinerary)

        assert has_conflicts
        assert len(conflicts) > 0


class TestBudgetTracker:
    """Test budget tracking."""

    def test_allocate_budget(self, sample_trip):
        """Test allocating trip budget."""
        tracker = BudgetTracker()

        allocations = {
            "flights": Decimal("2000"),
            "hotels": Decimal("2000"),
            "activities": Decimal("1000"),
        }

        result = tracker.allocate_budget("IT001", sample_trip.budget, allocations)

        assert result["total_budget"] == sample_trip.budget
        assert result["unallocated"] == Decimal("0")

    def test_allocate_budget_over_limit(self, sample_trip):
        """Test error when allocation exceeds budget."""
        tracker = BudgetTracker()

        allocations = {
            "flights": Decimal("3000"),
            "hotels": Decimal("3000"),
        }

        with pytest.raises(BookingError):
            tracker.allocate_budget("IT001", sample_trip.budget, allocations)

    def test_track_spending(self, sample_trip):
        """Test tracking spending against budget."""
        tracker = BudgetTracker()

        allocations = {
            "flights": Decimal("2000"),
            "hotels": Decimal("2000"),
            "activities": Decimal("1000"),
        }

        tracker.allocate_budget("IT001", sample_trip.budget, allocations)
        tracker.track_spending("IT001", "flights", Decimal("1500"))

        status = tracker.get_budget_status("IT001")
        assert status["remaining"] == Decimal("3500")

    def test_budget_exceeded(self, sample_trip):
        """Test error when spending exceeds allocated budget."""
        tracker = BudgetTracker()

        allocations = {"flights": Decimal("2000")}
        tracker.allocate_budget("IT001", Decimal("2000"), allocations)

        with pytest.raises(BookingError):
            tracker.track_spending("IT001", "flights", Decimal("2500"))


class TestItineraryIntegration:
    """Integration tests for itinerary operations."""

    def test_complete_itinerary_lifecycle(self, sample_trip, sample_flights, sample_activities):
        """Test complete itinerary creation, modification, and sharing."""
        # Assemble
        assembler = MultiSegmentAssembler()
        itinerary = assembler.assemble_trip(
            sample_trip,
            sample_flights,
            [],
            sample_activities,
        )

        # Optimize
        optimizer = ItineraryOptimizer()
        optimized = optimizer.minimize_wait_times(itinerary)

        # Version
        versioner = ItineraryVersioning()
        v1 = versioner.create_version(itinerary.itinerary_id, optimized, "Initial")

        # Share
        sharer = ItinerarySharing()
        sharer.share_itinerary(itinerary.itinerary_id, ["friend@example.com"])

        # Verify
        assert v1["version"] == 1
        assert "friend@example.com" in sharer.get_shared_users(itinerary.itinerary_id)
